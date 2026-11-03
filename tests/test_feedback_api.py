import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import app
import feedback_store


def jpeg_bytes(color: str = "green") -> bytes:
    image = Image.new("RGB", (40, 32), color)
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class FeedbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.client = TestClient(app.app)
        self.database_patch = patch.object(
            feedback_store, "DATABASE_PATH", self.root / "feedback.sqlite3"
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def detections() -> list[dict[str, object]]:
        return [
            {
                "class": "sigatoka",
                "confidence": 0.9,
                "x_center": 0.5,
                "y_center": 0.5,
                "width": 0.25,
                "height": 0.2,
            },
            {
                "class": "Healthy",
                "confidence": 0.8,
                "x_center": 0.5,
                "y_center": 0.5,
                "width": 0.8,
                "height": 0.8,
            },
        ]

    def submit_review(
        self,
        decision: str,
        *,
        image: bytes | None = None,
        annotations: list[dict[str, float]] | None = None,
    ):
        return self.client.post(
            "/api/feedback",
            data={
                "source": "gallery",
                "decision": decision,
                "detections_json": __import__("json").dumps(self.detections()),
                "annotations_json": __import__("json").dumps(
                    annotations if annotations is not None else []
                ),
            },
            files={
                "image": (
                    "leaf.jpg",
                    image if image is not None else jpeg_bytes(),
                    "image/jpeg",
                )
            },
        )

    def test_correct_feedback_saves_only_sigatoka_boxes(self) -> None:
        response = self.submit_review("correct")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["annotation_count"], 1)
        sample = feedback_store.get_reviewed_samples()[0]
        self.assertEqual(sample["decision"], "correct")
        self.assertEqual(
            sample["annotations"],
            [
                {
                    "x_center": 0.5,
                    "y_center": 0.5,
                    "width": 0.25,
                    "height": 0.2,
                }
            ],
        )

    def test_no_lesions_feedback_saves_empty_label(self) -> None:
        response = self.submit_review("no_lesions")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["annotation_count"], 0)
        self.assertEqual(feedback_store.get_reviewed_samples()[0]["annotations"], [])

    def test_edited_feedback_saves_manual_boxes(self) -> None:
        manual_box = {
            "x_center": 0.3,
            "y_center": 0.4,
            "width": 0.1,
            "height": 0.2,
        }
        response = self.submit_review("edited", annotations=[manual_box])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            feedback_store.get_reviewed_samples()[0]["annotations"],
            [manual_box],
        )

    def test_feedback_rejects_invalid_box_coordinates(self) -> None:
        response = self.submit_review(
            "edited",
            annotations=[
                {
                    "x_center": 1.4,
                    "y_center": 0.5,
                    "width": 0.2,
                    "height": 0.2,
                }
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(feedback_store.get_review_stats()["total"], 0)

    def test_feedback_stats(self) -> None:
        self.submit_review("correct")
        self.submit_review("no_lesions", image=jpeg_bytes("blue"))

        self.assertEqual(
            self.client.get("/api/feedback/stats").json(),
            {"total": 2, "correct": 1, "edited": 0, "no_lesions": 1},
        )

    def test_feedback_storage_can_be_disabled_for_hosted_service(self) -> None:
        with patch.object(app, "DISABLE_FEEDBACK_STORAGE", True):
            response = self.submit_review("correct")
            stats = self.client.get("/api/feedback/stats")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(stats.status_code, 403)
        self.assertEqual(feedback_store.get_review_stats()["total"], 0)

    def test_export_contains_reviewed_images_and_yolo_labels(self) -> None:
        self.submit_review("correct")
        self.submit_review("no_lesions", image=jpeg_bytes("blue"))

        base_archive = self.root / "base.zip"
        checkpoint = self.root / "model.pt"
        checkpoint.write_bytes(b"checkpoint")
        with zipfile.ZipFile(base_archive, "w") as archive:
            archive.writestr(
                "data.yaml",
                "train: train/images\nval: valid/images\ntest: test/images\n"
                "names:\n- Healthy\n- sigatoka\nnc: 2\n",
            )
            archive.writestr("train/images/existing.jpg", jpeg_bytes("red"))
            archive.writestr("train/labels/existing.txt", "1 0.5 0.5 0.2 0.2\n")
            archive.writestr("valid/images/validation.jpg", jpeg_bytes("yellow"))
            archive.writestr("test/images/test.jpg", jpeg_bytes("purple"))
            archive.writestr(app.TRAINING_CHECKPOINT_ENTRY, b"old checkpoint")

        with (
            patch.object(app, "BASE_TRAINING_ARCHIVE", base_archive),
            patch.object(app, "MODEL_PATH", checkpoint),
        ):
            export_path, stats = app.build_training_export()
        self.addCleanup(export_path.unlink, missing_ok=True)

        self.assertEqual(stats, {"included_samples": 2, "skipped_duplicates": 0})
        with zipfile.ZipFile(export_path) as archive:
            self.assertIsNone(archive.testzip())
            sample_names = [
                name
                for name in archive.namelist()
                if name.startswith("train/images/feedback_")
            ]
            self.assertEqual(len(sample_names), 2)
            for name in sample_names:
                label_name = name.replace("train/images/", "train/labels/").rsplit(
                    ".", 1
                )[0] + ".txt"
                label = archive.read(label_name).decode("utf-8")
                if label:
                    self.assertTrue(label.startswith("1 "))
            self.assertEqual(archive.read(app.TRAINING_CHECKPOINT_ENTRY), b"checkpoint")
            self.assertIn("feedback_manifest.csv", archive.namelist())
            self.assertEqual(
                sum(
                    name.startswith("valid/images/")
                    for name in archive.namelist()
                ),
                1,
            )

    def test_export_skips_image_with_different_jpeg_encoding(self) -> None:
        image = jpeg_bytes()
        self.submit_review("correct", image=image)

        base_archive = self.root / "base.zip"
        checkpoint = self.root / "model.pt"
        checkpoint.write_bytes(b"checkpoint")
        with zipfile.ZipFile(base_archive, "w") as archive:
            archive.writestr("train/images/existing.jpg", image)

        with (
            patch.object(app, "BASE_TRAINING_ARCHIVE", base_archive),
            patch.object(app, "MODEL_PATH", checkpoint),
        ):
            export_path, stats = app.build_training_export()
        self.addCleanup(export_path.unlink, missing_ok=True)

        self.assertEqual(stats, {"included_samples": 0, "skipped_duplicates": 1})
        with zipfile.ZipFile(export_path) as archive:
            self.assertFalse(
                any(
                    name.startswith("train/images/feedback_")
                    for name in archive.namelist()
                )
            )

    def test_export_without_base_archive_contains_reviewed_training_data(self) -> None:
        self.submit_review("correct")
        missing_archive = self.root / "not-present.zip"
        with patch.object(app, "BASE_TRAINING_ARCHIVE", missing_archive):
            export_path, stats = app.build_training_export()
        self.addCleanup(export_path.unlink, missing_ok=True)

        self.assertEqual(stats, {"included_samples": 1, "skipped_duplicates": 0})
        with zipfile.ZipFile(export_path) as archive:
            image_names = [
                name
                for name in archive.namelist()
                if name.startswith("train/images/feedback_")
            ]
            self.assertEqual(len(image_names), 1)
            label_name = image_names[0].replace(
                "train/images/", "train/labels/"
            ).rsplit(".", 1)[0] + ".txt"
            self.assertTrue(archive.read(label_name).decode("utf-8").startswith("1 "))
            self.assertIn("feedback/README.txt", archive.namelist())
            self.assertIn("feedback_manifest.csv", archive.namelist())

    def test_training_export_requires_configured_basic_auth(self) -> None:
        self.submit_review("correct")
        with (
            patch.object(app, "EXPORT_PASSWORD", "test-password"),
            patch.object(app, "BASE_TRAINING_ARCHIVE", self.root / "missing.zip"),
        ):
            unauthorized = self.client.get("/api/dataset/export")
            self.assertEqual(unauthorized.status_code, 401)

            response = self.client.get(
                "/api/dataset/export",
                auth=(app.EXPORT_USERNAME, "test-password"),
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            response.headers["content-disposition"].endswith(
                'filename="LeafCare-reviewed-feedback.zip"'
            )
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIsNone(archive.testzip())


if __name__ == "__main__":
    unittest.main()
