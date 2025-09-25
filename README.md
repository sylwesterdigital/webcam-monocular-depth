# Live Depth Point Cloud (Webcam → MiDaS → WebSocket → Three.js)

Real-time “holographic” point cloud in the browser.
Python reads a webcam, estimates per-pixel depth with MiDaS, streams depth+RGB over WebSocket; a Three.js client unprojects to 3D and renders a colored point cloud with **smooth tweening** between frames.

## Demo

https://github.com/user-attachments/assets/1cb5da49-d9f7-46f6-a85b-b25ac00eb140

---

## Features

* Monocular depth (MiDaS) — no extra hardware.
* Live colored point cloud in Three.js.
* **Inertia smoothing** in the client to hide low/irregular frame rates.
* Zero build step on the client (ESM + CDN import map).
* Binary protocol (compact): header JSON + depth32 + rgb8.
* Optional synthetic **TEST_PATTERN** for quick end-to-end checks.

---

## Repo layout

```
.
├─ server.py            # Python WebSocket depth streamer
└─ client/
   └─ index.html        # Three.js viewer (with tweened point motion)
```

---

## Quick start

### 1) Python env (macOS recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install opencv-python torch torchvision torchaudio pillow websockets numpy timm
```

### 2) Run the streamer

```bash
# Real webcam + MiDaS
python server.py

# Or: synthetic test pattern (no camera/model), proves client path
TEST_PATTERN=1 python server.py
```

The console shows: `Streaming on ws://localhost:8765 …`

> macOS: allow Camera access for the terminal app (System Settings → Privacy & Security → Camera).
> If webcam not found, try `WEBCAM_INDEX=1 python server.py`.

### 3) Open the viewer

Open `client/index.html` in a modern browser (Chrome recommended).
The overlay will show resolution and FPS; use the mouse to orbit/zoom.

---

## How it works

### Data flow

```
Webcam → OpenCV → MiDaS (PyTorch) → depth map
 → subsample/normalize → pack (header + depth + rgb)
 → WebSocket → Browser → unproject → Three.js Point cloud
 → tween between frames for smooth motion
```

### Binary frame format

```
[ uint32 header_len ]
[ header JSON (UTF-8) ]
[ 0..3 bytes padding to 4-byte boundary ]
[ depth  float32 array, length = w*h ]
[ rgb    uint8   array, length = 3*w*h ]
```

`header` contains: `{ w,h, fx,fy, cx,cy, stride, ts }`.

---

## Configuration (env vars)

| Var             | Default       | Meaning                                                   |
| --------------- | ------------- | --------------------------------------------------------- |
| `WEBCAM_INDEX`  | `0`           | Camera index for OpenCV.                                  |
| `TARGET_WIDTH`  | `640`         | Width used for inference (keeps aspect).                  |
| `STRIDE`        | `2`           | Subsampling factor (1 = full res).                        |
| `FOV_DEG`       | `60.0`        | Approx horizontal FOV for intrinsics.                     |
| `MODEL_TYPE`    | `MiDaS_small` | MiDaS variant (`MiDaS_small`, `DPT_Hybrid`, `DPT_Large`). |
| `EMA_ALPHA`     | `0.2`         | Temporal EMA smoothing of depth on server.                |
| `CLAMP_NEAR`    | `0.2`         | Near clamp of (pseudo-metric) depth.                      |
| `CLAMP_FAR`     | `4.0`         | Far clamp of depth.                                       |
| `TEST_PATTERN`  | `0`           | `1` = enable synthetic rotating plane.                    |
| `LOG_EVERY_SEC` | `2.0`         | Server stats log interval (seconds).                      |

Set via:

```bash
STRIDE=3 TARGET_WIDTH=800 MODEL_TYPE=DPT_Hybrid python server.py
```

---

## Client smoothing (tweening)

The client keeps three buffers:

* `lastPos` (previous positions),
* `nextPos` (latest positions from the network),
* `position` (rendered, CPU-mixed each `requestAnimationFrame`).

Blend window (`targetTweenMs`) adapts to network inter-arrival time (typ. 80–200 ms).
For heavier inertia, increase the initial value in `index.html`:

```js
let targetTweenMs = 160; // e.g., 160–240 for smoother glide
```

---

## Troubleshooting

* **Black screen, no overlay updates:** check that `server.py` prints `Streaming on ws://localhost:8765`; verify the browser devtools network/WebSocket shows traffic.
* **Camera not opening:** grant Camera permission; try `WEBCAM_INDEX=1`.
* **Very slow on CPU:** switch to `MiDaS_small` (default) or ensure Apple Silicon uses MPS (automatically selected).
* **Misaligned typed arrays:** server pads header to a 4-byte boundary; the client also aligns before reading `Float32Array`.

---

## License

MIT (or add your preferred license).
