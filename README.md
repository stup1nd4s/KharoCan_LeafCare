# LeafCare

LeafCare consists of a Flutter camera app and a FastAPI server. The app can
capture a photo when you tap **Capture and analyze**, or analyze a photo
selected from the gallery. The API runs the local YOLO detector in
`weights/new_combined_best.pt` and returns detected
boxes, each class's highest detection confidence, and an annotated image.

The local detector recognizes `Healthy` and `sigatoka`. It is an object
detector, not a multi-disease image classifier. Its confidence values apply to
detected objects and should not be interpreted as diagnostic certainty.
Inference runs on the PC (using CUDA when available); no Roboflow API key or
paid Roboflow inference is required.

## Run the API on Windows

The `.venv` environment contains the local PyTorch/Ultralytics runtime. From
this project directory, install dependencies if needed and run the server:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

The default model path is the latest fine-tuned checkpoint above. The previous
checkpoint is still available at `weights/leafcare_sigatoka_best.pt`. To use
another YOLO checkpoint, set `LEAFCARE_MODEL_PATH` before starting the server.
The default detection confidence threshold is 0.25; override it with
`LOCAL_DETECTION_CONFIDENCE` (a value from 0 to 1).
Set `LEAFCARE_EXPORT_PASSWORD` before starting the API to enable protected ZIP
exports. For a local PowerShell session, for example:

```powershell
$env:LEAFCARE_EXPORT_PASSWORD = [guid]::NewGuid().ToString()
.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

When opening the copied export URL in a browser, use username `leafcare-admin`
and that password.

Check the API at `http://localhost:8000/api/health`.

Run the local API contract tests without calling Roboflow:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Retrain the detector in Google Colab

Open [LeafCare_Train_YOLO.ipynb](./LeafCare_Train_YOLO.ipynb) in Google Colab.
Upload [LeafCare-combined-training.zip](./LeafCare-combined-training.zip) to
Google Drive at `MyDrive/LeafCare/LeafCare-combined-training.zip`. It contains
the original dataset, reviewed supplementary training images, and the current
checkpoint used to initialize fine-tuning. Supplementary validation/test
images are intentionally excluded because their candidate boxes were generated
by the current model. The notebook converts any remaining segmentation polygons
to detection boxes, reports class counts, fine-tunes the detector, and evaluates
it on the original held-out test split. Review the metrics and predictions
before replacing the API checkpoint; supplementary annotations may still have
missed lesions or other errors.

## Host the API on Render

The Render Blueprint is in [render.yaml](./render.yaml). It deploys the current
YOLO checkpoint with CPU-only PyTorch and creates a randomly generated password
to protect the training-data export. The API itself accepts analysis and
feedback uploads without a login, so share the service URL only with intended
users.

The configured **free** Render service is a demo. It can sleep after inactivity,
making its first request take about a minute, and its filesystem is temporary:
reviewed photos and the SQLite database can disappear when Render restarts or
redeploys the service. Inference also runs on CPU. On this PC, a CPU test took
4.64 seconds per 640-pixel image; Render's free CPU/memory limits may be tighter
and may not be sufficient for this YOLOv8m checkpoint. Confirm `/api/health`
and test image analysis after deployment. Persistent feedback storage requires
a paid Render service and persistent disk.

To publish, create a **private** GitHub repository and push this project. The
repository must include `weights/new_combined_best.pt`; `.gitignore` excludes
the `.env` secret file, training ZIPs, other model checkpoints, local database,
and virtual environments. In Render, connect the repository and create a
Blueprint from `render.yaml`. After Render assigns the service an `onrender.com`
URL, build/install the Android app with that URL:

```powershell
Set-Location flutter_app
flutter build apk --release --dart-define=API_BASE_URL=https://YOUR-SERVICE.onrender.com
```

The archive icon copies the protected `/api/dataset/export` URL. For a Render
deployment, open it in a browser and authenticate with username
`leafcare-admin` and the generated `LEAFCARE_EXPORT_PASSWORD` shown in the
Render service's environment settings. Because the base training ZIP is
intentionally not deployed, the endpoint downloads
`LeafCare-reviewed-feedback.zip`, containing supplementary training images and
YOLO labels only. Upload that ZIP to
`MyDrive/LeafCare/LeafCare-reviewed-feedback.zip`; the Colab notebook merges its
images/labels into the base dataset's training split when the archive is
present. The feedback export does not contain the base dataset or checkpoint.

## Run the Android app locally

From `flutter_app`, install Flutter dependencies and run on a connected device:

```powershell
Set-Location flutter_app
flutter pub get
flutter run -d <phone-device-id>
```

The default phone API URL is `http://192.168.254.103:8000`; update
`API_BASE_URL` in `flutter_app/lib/main.dart` or pass
`--dart-define=API_BASE_URL=http://<current-PC-Wi-Fi-IP>:8000` if the PC's
Wi-Fi address changes. Keep the phone and PC on the same Wi-Fi network. If the
phone cannot load `/api/health`, allow inbound TCP port 8000 through Windows
Firewall and check that the router does not isolate wireless clients.

Keep the API server running while using the app. The API accepts images up to
10 MB and performs inference on the PC.

## Review images and export training data

The app can analyze a camera photo or an image selected from the gallery. After
analysis, choose one of the review actions:

- **Correct** saves the model's Sigatoka boxes as reviewed labels.
- **Edit boxes** opens the annotation editor. Drag on the image to draw boxes;
  remove boxes or clear them before saving.
- **No Sigatoka** saves an explicitly reviewed image with an empty label.

When running locally, reviewed images and annotations are stored on the PC in
`data\feedback.sqlite3` (override the path with `LEAFCARE_DATABASE_PATH`). In
Render, they are sent to the cloud service instead; free Render storage is
temporary. Only reviewed samples are included in training exports.

To export the latest training ZIP:

1. Keep the API running and make sure `LeafCare-combined-training.zip` and the
   active model checkpoint exist in the project directory.
2. In the app, tap the archive icon to copy the export URL, then open that URL
   in a browser on the PC. Alternatively, open
   `http://localhost:8000/api/dataset/export` on the PC.
3. Save the downloaded `LeafCare-combined-training.zip` and upload it to
   `MyDrive/LeafCare/LeafCare-combined-training.zip` in Google Drive before
   running the Colab notebook.

The export adds reviewed images and YOLO labels to the training split,
replaces the checkpoint entry with the currently configured model, and leaves
the base validation/test splits unchanged. Exact image duplicates are skipped.
It also includes `feedback_manifest.csv` and `feedback/README.txt`. Keep a copy
of the original ZIP; this endpoint creates a new download and does not overwrite
the base ZIP on disk.

The Android manifest allows cleartext HTTP for local development. Use the
Render HTTPS URL for a hosted build. The training export requires HTTP Basic
authentication, but image analysis and feedback submission do not; do not share
the hosted API URL publicly or send sensitive images to it.
