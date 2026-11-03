import base64
import io
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

import app


def encoded_test_image() -> bytes:
    image_data = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(image_data, format="JPEG")
    return image_data.getvalue()


class FakeBox:
    cls = [1]
    conf = [0.9]
    xywh = [[16, 16, 10, 8]]


class FakeResult:
    names = {0: "Healthy", 1: "sigatoka"}

    def __init__(self, boxes):
        self.boxes = boxes


class LocalInferenceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app.app)
        self.model = Mock()
        self.model.predict.return_value = [FakeResult([FakeBox()])]

    def test_analyze_returns_local_detections_and_annotated_image(self) -> None:
        with patch.object(app, "get_local_model", return_value=self.model):
            response = self.client.post(
                "/api/analyze",
                files={"image": ("leaf.jpg", encoded_test_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {
                "annotated_image_base64",
                "class_confidences",
                "detections",
                "detection_count",
                "summary",
            },
        )
        self.assertEqual(payload["detection_count"], 1)
        self.assertEqual(payload["class_confidences"], {"sigatoka": 0.9})
        self.assertEqual(
            payload["detections"],
            [
                {
                    "class": "sigatoka",
                    "confidence": 0.9,
                    "x_center": 0.5,
                    "y_center": 0.5,
                    "width": 10 / 32,
                    "height": 8 / 32,
                }
            ],
        )
        self.assertIn("1 possible Sigatoka lesion detected", payload["summary"])
        self.model.predict.assert_called_once()
        self.assertEqual(self.model.predict.call_args.kwargs["conf"], 0.25)
        self.assertEqual(self.model.predict.call_args.kwargs["imgsz"], 640)
        annotated = Image.open(
            io.BytesIO(base64.b64decode(payload["annotated_image_base64"]))
        )
        self.assertEqual(annotated.size, (32, 32))

    def test_analyze_reports_empty_detections(self) -> None:
        self.model.predict.return_value = [FakeResult([])]
        with patch.object(app, "get_local_model", return_value=self.model):
            response = self.client.post(
                "/api/analyze",
                files={"image": ("leaf.jpg", encoded_test_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["detection_count"], 0)
        self.assertEqual(payload["class_confidences"], {})
        self.assertEqual(payload["detections"], [])
        self.assertIn("No possible Sigatoka lesions", payload["summary"])

    def test_healthy_detections_are_not_counted_as_lesions(self) -> None:
        healthy_box = Mock(cls=[0], conf=[0.99], xywh=[[16, 16, 10, 8]])
        self.model.predict.return_value = [FakeResult([healthy_box])]
        with patch.object(app, "get_local_model", return_value=self.model):
            response = self.client.post(
                "/api/analyze",
                files={"image": ("leaf.jpg", encoded_test_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["detection_count"], 0)
        self.assertEqual(payload["class_confidences"], {"Healthy": 0.99})
        self.assertIn("No possible Sigatoka lesions", payload["summary"])

    def test_analyze_reports_missing_local_model(self) -> None:
        with patch.object(
            app, "get_local_model", side_effect=FileNotFoundError("missing best.pt")
        ):
            response = self.client.post(
                "/api/analyze",
                files={"image": ("leaf.jpg", encoded_test_image(), "image/jpeg")},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("missing best.pt", response.json()["detail"])

    def test_analyze_rejects_non_image_upload(self) -> None:
        response = self.client.post(
            "/api/analyze",
            files={"image": ("leaf.jpg", b"not an image", "image/jpeg")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"], "The uploaded file is not a valid image."
        )

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
