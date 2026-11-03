"""Serve local banana-leaf predictions to the LeafCare Flutter app."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import shutil
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from starlette.background import BackgroundTask
from ultralytics import YOLO

import feedback_store

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent
    / "weights"
    / "new_combined_best.pt"
)
MODEL_PATH = Path(os.getenv("LEAFCARE_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
BASE_TRAINING_ARCHIVE = (
    Path(__file__).resolve().parent / "LeafCare-combined-training.zip"
)
TRAINING_CHECKPOINT_ENTRY = "initial_weights/leafcare_sigatoka_best.pt"

try:
    DETECTION_CONFIDENCE = float(os.getenv("LOCAL_DETECTION_CONFIDENCE", "0.25"))
except ValueError as exc:
    raise RuntimeError(
        "LOCAL_DETECTION_CONFIDENCE must be a number between 0 and 1."
    ) from exc
if not 0 <= DETECTION_CONFIDENCE <= 1:
    raise RuntimeError("LOCAL_DETECTION_CONFIDENCE must be between 0 and 1.")

MAX_IMAGE_BYTES = 10 * 1024 * 1024
EXPORT_USERNAME = "leafcare-admin"
EXPORT_PASSWORD = os.getenv("LEAFCARE_EXPORT_PASSWORD")
export_auth = HTTPBasic(auto_error=False)

app = FastAPI(title="LeafCare Inference API")


@lru_cache(maxsize=1)
def get_local_model() -> YOLO:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"Local YOLO model was not found at {MODEL_PATH}. "
            "Set LEAFCARE_MODEL_PATH to the trained best.pt file."
        )
    return YOLO(str(MODEL_PATH))


def run_local_inference(
    image: Image.Image,
) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
    """Run the trained detector and return boxes plus best confidence per class."""
    results = get_local_model().predict(
        source=image,
        conf=DETECTION_CONFIDENCE,
        verbose=False,
    )
    if len(results) != 1:
        raise RuntimeError("The local model did not return exactly one image result.")

    result = results[0]
    detections: list[dict[str, Any]] = []
    class_confidences: dict[str, float] = {}
    if result.boxes is not None:
        for box in result.boxes:
            class_id = int(box.cls[0])
            label = result.names[class_id]
            confidence = float(box.conf[0])
            x, y, width, height = (float(value) for value in box.xywh[0])
            detections.append(
                {
                    "class": label,
                    "confidence": confidence,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
            class_confidences[label] = max(
                class_confidences.get(label, 0.0), confidence
            )

    normalized_detections = [
        {
            "class": detection["class"],
            "confidence": detection["confidence"],
            "x_center": detection["x"] / image.width,
            "y_center": detection["y"] / image.height,
            "width": detection["width"] / image.width,
            "height": detection["height"] / image.height,
        }
        for detection in detections
    ]
    return detections, class_confidences, normalized_detections


def annotate_detections(
    image: Image.Image,
    predictions: list[dict[str, Any]],
) -> Image.Image:
    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default(size=10)
    image_width, image_height = annotated.size

    for prediction in predictions:
        label = prediction["class"]
        x = float(prediction["x"])
        y = float(prediction["y"])
        width = float(prediction["width"])
        height = float(prediction["height"])
        confidence = float(prediction["confidence"])
        if not all(
            math.isfinite(value) for value in (x, y, width, height, confidence)
        ):
            continue

        x1 = max(0, round(x - width / 2))
        y1 = max(0, round(y - height / 2))
        x2 = min(image_width - 1, round(x + width / 2))
        y2 = min(image_height - 1, round(y + height / 2))

        draw.rectangle((x1, y1, x2, y2), outline="red", width=3)
        caption = f"{label} {confidence:.0%}"
        text_x = min(x1 + 2, max(0, image_width - 1))
        text_y = min(y1 + 2, max(0, image_height - 1))
        text_box = draw.textbbox((text_x, text_y), caption, font=font)
        draw.rectangle(text_box, fill="red")
        draw.text((text_x, text_y), caption, fill="white", font=font)

    return annotated


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze_leaf(image: UploadFile = File(...)) -> dict[str, Any]:
    image_data = image.file.read(MAX_IMAGE_BYTES + 1)
    if not image_data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(image_data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The uploaded image must be 10 MB or smaller.",
        )

    try:
        with Image.open(io.BytesIO(image_data)) as uploaded_image:
            leaf_image = uploaded_image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=400, detail="The uploaded file is not a valid image."
        ) from exc

    try:
        detections, class_confidences, normalized_detections = run_local_inference(
            leaf_image
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Local inference failed: {exc}"
        ) from exc

    lesion_detections = [
        detection
        for detection in detections
        if detection["class"].casefold() == "sigatoka"
    ]
    annotated = annotate_detections(leaf_image, lesion_detections)
    output = io.BytesIO()
    annotated.save(output, format="JPEG", quality=85)

    detection_count = len(lesion_detections)
    if detection_count:
        summary = (
            f"{detection_count} possible Sigatoka lesion"
            f"{'s' if detection_count != 1 else ''} detected."
        )
    else:
        summary = (
            "No possible Sigatoka lesions detected at the current threshold "
            f"({DETECTION_CONFIDENCE:.0%})."
        )

    return {
        "annotated_image_base64": base64.b64encode(output.getvalue()).decode("ascii"),
        "class_confidences": class_confidences,
        "detections": normalized_detections,
        "detection_count": detection_count,
        "summary": summary,
    }


def _validate_detections(value: Any) -> list[dict[str, Any]]:
    try:
        detections = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Detection feedback must be valid JSON."
        ) from exc
    if not isinstance(detections, list) or len(detections) > 500:
        raise HTTPException(
            status_code=400, detail="Detection feedback must be a list of at most 500 boxes."
        )

    validated = []
    for detection in detections:
        if not isinstance(detection, dict):
            raise HTTPException(status_code=400, detail="Invalid model detection.")
        label = detection.get("class")
        if label not in {"Healthy", "sigatoka"}:
            raise HTTPException(status_code=400, detail="Invalid model detection class.")
        values = {}
        for key in ("confidence", "x_center", "y_center", "width", "height"):
            raw_value = detection.get(key)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise HTTPException(
                    status_code=400, detail="Model detections must contain numeric box values."
                )
            number = float(raw_value)
            if not math.isfinite(number) or not 0 <= number <= 1:
                raise HTTPException(
                    status_code=400, detail="Model detection values must be between 0 and 1."
                )
            values[key] = number
        if values["width"] <= 0 or values["height"] <= 0:
            raise HTTPException(status_code=400, detail="Model detection boxes must have area.")
        validated.append({"class": label, **values})
    return validated


def _normalize_image_to_jpeg(image_data: bytes) -> bytes:
    with Image.open(io.BytesIO(image_data)) as uploaded_image:
        normalized_image = uploaded_image.convert("RGB")
        output = io.BytesIO()
        normalized_image.save(output, format="JPEG", quality=95)
        return output.getvalue()


def _validate_annotations(value: Any) -> list[dict[str, float]]:
    try:
        annotations = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Annotations must be valid JSON."
        ) from exc
    if not isinstance(annotations, list) or len(annotations) > 500:
        raise HTTPException(
            status_code=400, detail="Annotations must be a list of at most 500 boxes."
        )

    validated = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise HTTPException(status_code=400, detail="Invalid annotation box.")
        box = {}
        for key in ("x_center", "y_center", "width", "height"):
            raw_value = annotation.get(key)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise HTTPException(
                    status_code=400, detail="Annotation box values must be numeric."
                )
            number = float(raw_value)
            if not math.isfinite(number) or not 0 <= number <= 1:
                raise HTTPException(
                    status_code=400, detail="Annotation values must be between 0 and 1."
                )
            box[key] = number
        if box["width"] <= 0 or box["height"] <= 0:
            raise HTTPException(
                status_code=400, detail="Annotation boxes must have positive area."
            )
        validated.append(box)
    return validated


@app.post("/api/feedback")
def save_feedback(
    image: UploadFile = File(...),
    source: str = Form(...),
    decision: str = Form(...),
    detections_json: str = Form(...),
    annotations_json: str = Form(...),
) -> dict[str, Any]:
    if source not in {"camera", "gallery"}:
        raise HTTPException(status_code=400, detail="Source must be camera or gallery.")
    if decision not in {"correct", "edited", "no_lesions"}:
        raise HTTPException(status_code=400, detail="Invalid review decision.")

    image_data = image.file.read(MAX_IMAGE_BYTES + 1)
    if not image_data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(image_data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="The uploaded image must be 10 MB or smaller."
        )
    try:
        image_jpeg = _normalize_image_to_jpeg(image_data)
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=400, detail="The uploaded file is not a valid image."
        ) from exc

    detections = _validate_detections(detections_json)
    submitted_annotations = _validate_annotations(annotations_json)
    if decision == "correct":
        annotations = [
            {
                key: detection[key]
                for key in ("x_center", "y_center", "width", "height")
            }
            for detection in detections
            if detection["class"].casefold() == "sigatoka"
        ]
    elif decision == "no_lesions":
        annotations = []
    else:
        annotations = submitted_annotations

    sample_id = feedback_store.save_reviewed_sample(
        source=source,
        decision=decision,
        image_jpeg=image_jpeg,
        detections=detections,
        annotations=annotations,
    )
    return {
        "id": sample_id,
        "decision": decision,
        "annotation_count": len(annotations),
        "message": "Reviewed image saved to the local training database.",
    }


@app.get("/api/feedback/stats")
def feedback_stats() -> dict[str, int]:
    return feedback_store.get_review_stats()


def _write_zip_file(
    output_archive: zipfile.ZipFile,
    name: str,
    content: bytes,
) -> None:
    with output_archive.open(name, "w") as destination:
        destination.write(content)


def _write_feedback_samples(
    output_archive: zipfile.ZipFile,
    samples: list[dict[str, Any]],
) -> tuple[int, int]:
    known_image_hashes: set[str] = set()
    included_samples = 0
    duplicate_count = 0
    for sample in samples:
        digest = hashlib.sha256(sample["image_jpeg"]).hexdigest()
        if digest in known_image_hashes:
            duplicate_count += 1
            continue
        known_image_hashes.add(digest)
        image_name = f"train/images/feedback_{sample['id']}.jpg"
        label_name = f"train/labels/feedback_{sample['id']}.txt"
        label_rows = [
            "1 "
            + " ".join(
                f"{annotation[key]:.8f}"
                for key in ("x_center", "y_center", "width", "height")
            )
            for annotation in sample["annotations"]
        ]
        _write_zip_file(output_archive, image_name, sample["image_jpeg"])
        _write_zip_file(
            output_archive,
            label_name,
            ("\n".join(label_rows) + ("\n" if label_rows else "")).encode("utf-8"),
        )
        included_samples += 1
    return included_samples, duplicate_count


def _write_feedback_manifest(samples: list[dict[str, Any]]) -> bytes:
    manifest_rows = [["id", "created_at", "source", "decision", "annotations"]]
    manifest_rows.extend(
        [
            sample["id"],
            sample["created_at"],
            sample["source"],
            sample["decision"],
            str(len(sample["annotations"])),
        ]
        for sample in samples
    )
    manifest_buffer = io.StringIO(newline="")
    csv.writer(manifest_buffer).writerows(manifest_rows)
    return manifest_buffer.getvalue().encode("utf-8")


def build_training_export() -> tuple[Path, dict[str, int]]:
    samples = feedback_store.get_reviewed_samples()
    export_path = Path(tempfile.gettempdir()) / f"leafcare-export-{uuid4().hex}.zip"
    if not BASE_TRAINING_ARCHIVE.is_file():
        try:
            with zipfile.ZipFile(
                export_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
            ) as output_archive:
                included_samples, duplicate_count = _write_feedback_samples(
                    output_archive, samples
                )
                _write_zip_file(
                    output_archive,
                    "feedback_manifest.csv",
                    _write_feedback_manifest(samples),
                )
                notes = (
                    "Reviewed LeafCare feedback samples for Colab.\n"
                    "This is a supplementary archive only; it does not contain "
                    "the base dataset or model checkpoint.\n"
                    "Merge train/images and train/labels into the base dataset's "
                    "training split before training.\n"
                    f"Included feedback samples: {included_samples}. "
                    f"Skipped duplicate feedback images: {duplicate_count}.\n"
                ).encode("utf-8")
                _write_zip_file(output_archive, "feedback/README.txt", notes)
        except Exception:
            export_path.unlink(missing_ok=True)
            raise
        return export_path, {
            "included_samples": included_samples,
            "skipped_duplicates": duplicate_count,
        }

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Current model checkpoint was not found at {MODEL_PATH}.")
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    known_image_hashes: set[str] = set()
    added_samples = []
    duplicate_count = 0

    try:
        with zipfile.ZipFile(BASE_TRAINING_ARCHIVE) as base_archive:
            if base_archive.testzip() is not None:
                raise ValueError("The base training dataset ZIP failed its integrity check.")
            for name in base_archive.namelist():
                parts = Path(name).parts
                if (
                    len(parts) >= 3
                    and parts[0] in {"train", "valid", "test"}
                    and parts[1] == "images"
                    and Path(name).suffix.lower() in image_suffixes
                ):
                    try:
                        canonical_image = _normalize_image_to_jpeg(
                            base_archive.read(name)
                        )
                    except (UnidentifiedImageError, OSError) as exc:
                        raise ValueError(
                            f"Dataset image {name} is not a valid image."
                        ) from exc
                    digest = hashlib.sha256(canonical_image).hexdigest()
                    known_image_hashes.add(digest)
            for sample in samples:
                digest = hashlib.sha256(sample["image_jpeg"]).hexdigest()
                if digest in known_image_hashes:
                    duplicate_count += 1
                    continue
                known_image_hashes.add(digest)
                added_samples.append(sample)

            checkpoint_bytes = MODEL_PATH.read_bytes()
            notes = (
                "Reviewed feedback exported from the local LeafCare SQLite database.\n"
                "Feedback images are added to TRAIN only; the base validation and test splits are unchanged.\n"
                "Only exact-image duplicates were skipped. Images may be uploaded repeatedly with different crops.\n"
                "Human review decisions: correct accepts model Sigatoka boxes; edited uses hand-drawn boxes; "
                "no_lesions is an explicitly verified empty label.\n"
                f"Included feedback samples: {len(added_samples)}. "
                f"Skipped exact duplicates: {duplicate_count}.\n"
                f"Training checkpoint refreshed from {MODEL_PATH.name}.\n"
            ).encode("utf-8")
            with zipfile.ZipFile(
                export_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
            ) as output_archive:
                for info in base_archive.infolist():
                    if info.filename in {
                        TRAINING_CHECKPOINT_ENTRY,
                        "feedback_manifest.csv",
                        "feedback/README.txt",
                    }:
                        continue
                    if info.filename.endswith(".cache"):
                        continue
                    with base_archive.open(info) as source, output_archive.open(
                        info, "w"
                    ) as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                _write_zip_file(
                    output_archive,
                    TRAINING_CHECKPOINT_ENTRY,
                    checkpoint_bytes,
                )
                _write_zip_file(
                    output_archive,
                    "feedback_manifest.csv",
                    _write_feedback_manifest(added_samples),
                )
                _write_zip_file(output_archive, "feedback/README.txt", notes)
                _write_feedback_samples(output_archive, added_samples)
    except Exception:
        export_path.unlink(missing_ok=True)
        raise

    return export_path, {
        "included_samples": len(added_samples),
        "skipped_duplicates": duplicate_count,
    }


def require_export_auth(
    credentials: HTTPBasicCredentials | None = Depends(export_auth),
) -> None:
    if not EXPORT_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Training export authentication is not configured.",
        )
    if (
        credentials is None
        or not hmac.compare_digest(credentials.username, EXPORT_USERNAME)
        or not hmac.compare_digest(credentials.password, EXPORT_PASSWORD)
    ):
        raise HTTPException(
            status_code=401,
            detail="Training export credentials are invalid.",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/api/dataset/export")
def download_training_export(
    _: None = Depends(require_export_auth),
) -> FileResponse:
    try:
        export_path, _ = build_training_export()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not build the training ZIP: {exc}"
        ) from exc
    filename = (
        "LeafCare-combined-training.zip"
        if BASE_TRAINING_ARCHIVE.is_file()
        else "LeafCare-reviewed-feedback.zip"
    )
    return FileResponse(
        export_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(export_path.unlink, missing_ok=True),
    )
