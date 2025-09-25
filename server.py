# server.py
# macOS / Python 3.10+ recommended
# pip install opencv-python torch torchvision torchaudio pillow websockets numpy

import asyncio, struct, json, time
import cv2
import numpy as np
import torch
import torchvision.transforms as T
import websockets

# ---------- config ----------
WEBCAM_INDEX = 0
TARGET_WIDTH = 640            # resize for inference & streaming
STRIDE = 2                    # subsample pixels for fewer points (1=full res; try 2–4)
FOV_DEG = 60.0                # horizontal FOV guess; refine with calibration if desired
PORT = 8765
MODEL_TYPE = "DPT_Small"      # good quality/speed tradeoff on CPU
EMA_ALPHA = 0.2               # temporal smoothing of depth [0..1], higher = smoother
# ----------------------------

# MiDaS setup
device = torch.device("mps" if torch.backends.mps.is_available() else
                      "cuda" if torch.cuda.is_available() else "cpu")

MODEL_TYPE = "MiDaS_small"  # valid options: "MiDaS_small", "DPT_Large", "DPT_Hybrid"

midas = torch.hub.load("intel-isl/MiDaS", MODEL_TYPE, trust_repo=True).to(device).eval()
midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)

# choose the correct transform for the model
if MODEL_TYPE in ["DPT_Large", "DPT_Hybrid"]:
    transform = midas_transforms.dpt_transform
else:
    transform = midas_transforms.small_transform


# Camera
cap = cv2.VideoCapture(WEBCAM_INDEX)
if not cap.isOpened():
    raise RuntimeError("Cannot open webcam")

# Intrinsics (approx) from FOV + width/height
def intrinsics(w, h, fov_deg):
    f = 0.5 * w / np.tan(np.deg2rad(fov_deg) / 2.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    return f, f, cx, cy

# Depth normalization helper (MiDaS outputs inverse-scale depth)
def normalize_depth(d):
    d = d - d.min()
    if d.max() > 0:
        d = d / d.max()
    # map to pseudo-meters (relative). Rescale so typical range ~ 0.2..4.0
    return 0.2 + 3.8 * d

ema_depth = None

# Pack format:
# [header_len(uint32)][header_bytes(JSON)]
# [depth(float32, N)][rgb(uint8, 3*N)]
async def frame_stream(websocket):
    global ema_depth
    while True:
        ok, frame = cap.read()
        if not ok:
            continue

        # Resize (keep aspect)
        h0, w0 = frame.shape[:2]
        scale = TARGET_WIDTH / float(w0)
        w, h = int(w0 * scale), int(h0 * scale)
        frame_s = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)

        # MiDaS expects RGB
        rgb = cv2.cvtColor(frame_s, cv2.COLOR_BGR2RGB)

        # Depth inference
        with torch.no_grad():
            inp = transform(rgb).to(device)
            pred = midas(inp)
            depth = torch.nn.functional.interpolate(
                pred.unsqueeze(1),
                size=(h, w),
                mode="bicubic",
                align_corners=False
            ).squeeze().cpu().numpy()

        # Normalize & temporal smooth
        d_norm = normalize_depth(depth)
        if ema_depth is None:
            ema_depth = d_norm
        else:
            ema_depth = EMA_ALPHA * d_norm + (1.0 - EMA_ALPHA) * ema_depth

        # Subsample to reduce payload
        d_sub = ema_depth[::STRIDE, ::STRIDE].astype(np.float32)
        rgb_sub = rgb[::STRIDE, ::STRIDE].reshape(-1, 3).astype(np.uint8)

        hs, ws = d_sub.shape[:2]
        fx, fy, cx, cy = intrinsics(ws, hs, FOV_DEG)

        header = {
            "w": int(ws), "h": int(hs),
            "fx": float(fx), "fy": float(fy),
            "cx": float(cx), "cy": float(cy),
            "stride": int(STRIDE),
            "ts": time.time()
        }
        header_bytes = json.dumps(header).encode("utf-8")
        header_len = struct.pack("<I", len(header_bytes))

        payload = [
            header_len,
            header_bytes,
            d_sub.tobytes(order="C"),
            rgb_sub.tobytes(order="C"),
        ]

        try:
            await websocket.send(b"".join(payload))
        except Exception:
            break

        await asyncio.sleep(0)  # yield to event loop

async def handler(websocket):
    # send one hello message so client can confirm connection
    await websocket.send(struct.pack("<I", 0))
    await frame_stream(websocket)

async def main():
    async with websockets.serve(handler, "localhost", PORT, max_size=None):
        print(f"Streaming on ws://localhost:{PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        cap.release()

