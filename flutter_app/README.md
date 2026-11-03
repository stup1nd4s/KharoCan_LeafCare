# LeafCare Flutter app

The app shows a live camera preview or lets you choose an image from the
gallery. It sends the selected photo to the LeafCare API and displays the
returned detection count, detected classes, and annotated image.

## Run on a phone over Wi-Fi

1. Start the API from `C:\Python Projects` so it listens on the PC's network
   interfaces:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
   ```

2. Keep the phone and PC on the same Wi-Fi network. The app defaults to the
   hosted Render API. To use the PC API, pass its Wi-Fi address through
   `API_BASE_URL`.
3. If the phone cannot load `http://192.168.254.103:8000/api/health`, allow inbound
   TCP port 8000 for Python/Uvicorn in Windows Firewall on the active network.
   Also check that the router does not isolate wireless clients from each
   other. A weak Wi-Fi signal can interrupt larger photo uploads even when the
   phone can load the small health response.
4. Install or update the app from this directory:

   ```powershell
   flutter run -d <phone-device-id> --dart-define=API_BASE_URL=http://192.168.254.103:8000 --dart-define=ENABLE_FEEDBACK_UPLOAD=true
   ```

USB or wireless debugging is needed to install/run the development build from
the PC, but not for the installed app to use the API over Wi-Fi. Keep the API
server running while capturing. Inference runs locally on the PC with the
trained `Healthy`/`sigatoka` YOLO detector; it does not call Roboflow. The
detector's confidence is for detected objects, not a medical diagnosis. If the
health URL works but analysis fails, use the app error and API terminal output
to diagnose local model inference.

## Use a hosted Render API

After deploying the API, build the Android app with the Render HTTPS URL so it
does not depend on the PC:

```powershell
flutter build apk --release --dart-define=API_BASE_URL=https://YOUR-SERVICE.onrender.com
```

Install the resulting `build\app\outputs\flutter-apk\app-release.apk`. The free
Render demo may sleep and take about a minute to wake. CPU inference may also
be slower than on the PC; the currently deployed free service has not passed
an image-analysis test yet. Hosted review uploads are disabled, so reviewed
photos are not sent to Render.

## Review and export training data

For a local API build with `ENABLE_FEEDBACK_UPLOAD=true`, after analysis select
**Correct** to accept the predicted Sigatoka boxes,
**Edit boxes** to draw or remove boxes manually, or **No Sigatoka** to save an
explicitly reviewed empty label. The API stores only reviewed images and
annotations on the PC in `data\feedback.sqlite3`; it does not send them to a
cloud service.

The archive icon copies the ZIP export URL when feedback uploads are enabled.
Open the copied URL in a browser on the PC to download reviewed data. Local
reviews are stored in `data\feedback.sqlite3`. Hosted builds hide the review
controls by default and the Render API rejects feedback uploads.
