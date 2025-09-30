# LiveDepth

<img width="5120" height="2880" alt="pointcloud_2025-09-27_00-08-53" src="https://github.com/user-attachments/assets/cdc896fe-c3b6-4335-ab0e-7a53d9571995" />

LiveDepth is a **real-time monocular depth streaming app** for macOS.  
It uses **PyTorch MiDaS models** to infer per-pixel depth from a webcam feed (or a synthetic test pattern), and streams results over **WebSockets** to a browser-based 3D viewer.  

It runs locally, requires no cloud connection, and packages into a standalone `.app` with HTTPS UI and WSS data channel.

---

## Features

- Monocular depth estimation in real-time using MiDaS (`MiDaS_small`, `DPT_Hybrid`, or `DPT_Large`).
- Camera feed (FaceTime HD, external USB, or virtual webcams) or synthetic test pattern.
- Streams depth + RGB frames via **WebSocket**.
- Local **HTTPS server** hosts the UI viewer.
- Status-bar app bundle for macOS with:
  - Open Viewer
  - Restart Server
  - About panel (with version/build metadata)
  - Quit

---

## Requirements

- **macOS 11.0+** (Apple Silicon recommended).
- Python **3.10+** (tested with 3.13).
- [Homebrew](https://brew.sh/) (to install `ffmpeg` and `mkcert`).
- Dependencies (install inside a venv):

```
  pip install opencv-python torch torchvision torchaudio pillow websockets numpy timm pyobjc
```

---

## Running Locally (Source Tree)

### 1. Clone and set up environment

```
git clone https://github.com/sylwesterdigital/webcam-monocular-depth
cd webcam-monocular-depth
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Generate HTTPS certificates (first run only)

```
cd client
mkdir -p certs && cd certs
brew install mkcert nss
mkcert -install
mkcert localhost 127.0.0.1 ::1
```

### 3. Test run (without build)

Use test pattern (no camera):

```
./test.sh
```

Or use webcam:

```
./test.sh --camera
```

This launches:

* HTTPS UI at [https://127.0.0.1:8443](https://127.0.0.1:8443)
* WebSocket server at `ws(s)://127.0.0.1:8765/`

---

## Building macOS `.app`

We use **PyInstaller** with a custom `LiveDepth.spec`.

### 1. Ensure you have pyinstaller

```
pip install pyinstaller
```

### 2. Create app icon

```
mkdir -p build/Icon.iconset assets
sips -z 16 16     icon.png --out build/Icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out build/Icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out build/Icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out build/Icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out build/Icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out build/Icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out build/Icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out build/Icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out build/Icon.iconset/icon_512x512.png
sips -z 1024 1024 icon.png --out build/Icon.iconset/icon_512x512@2x.png
iconutil -c icns build/Icon.iconset -o assets/LiveDepth.icns
```

### 3. Build

```bash
pyinstaller LiveDepth.spec --noconfirm
```

The result is in:

```
dist/LiveDepth.app
```

Move it to `/Applications` if desired.

---

## Usage

* Launch `LiveDepth.app` from Finder.
* A status-bar icon appears (`LiveDepth`).
* Menu options:

  * **About LiveDepth** — shows version/build info
  * **Open Viewer** — opens the browser client
  * **Restart Server** — restarts depth inference
  * **Quit LiveDepth** — exits

---

## Configuration

Set via environment variables:

* `WEBCAM_INDEX=0` — select camera by index
* `WEBCAM_NAME="FaceTime HD Camera"` — select camera by name (macOS/AVFoundation)
* `MODEL_TYPE=MiDaS_small|DPT_Hybrid|DPT_Large`
* `TEST_PATTERN=1` — use synthetic scene (for debugging)
* `TARGET_WIDTH=640` — resize input width
* `STRIDE=2` — subsample for performance/bandwidth

---

## License

© 2025 Sylwester Mielniczuk — WORKWORK.FUN LTD (UK).
All rights reserved.
