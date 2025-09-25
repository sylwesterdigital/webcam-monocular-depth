# server.py
# macOS / Python 3.10+ recommended
# pip install opencv-python torch torchvision torchaudio pillow websockets numpy timm

import asyncio, struct, json, time, os, logging
import cv2
import numpy as np
import torch
import websockets

# ------------------------ config ------------------------
WEBCAM_INDEX = int(os.getenv("WEBCAM_INDEX", "0"))
TARGET_WIDTH = int(os.getenv("TARGET_WIDTH", "640"))
STRIDE = int(os.getenv("STRIDE", "2"))                # 1=full res; 2/3 reduces payload
FOV_DEG = float(os.getenv("FOV_DEG", "60.0"))
PORT = int(os.getenv("PORT", "8765"))
MODEL_TYPE = os.getenv("MODEL_TYPE", "MiDaS_small")   # "MiDaS_small" | "DPT_Large" | "DPT_Hybrid"
EMA_ALPHA = float(os.getenv("EMA_ALPHA", "0.2"))
CLAMP_NEAR = float(os.getenv("CLAMP_NEAR", "0.2"))
CLAMP_FAR  = float(os.getenv("CLAMP_FAR", "4.0"))
TEST_PATTERN = bool(int(os.getenv("TEST_PATTERN", "0")))  # 1 = synth rotating slab to debug client
LOG_EVERY_SEC = float(os.getenv("LOG_EVERY_SEC", "2.0"))
# --------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("depth-stream")

device = torch.device("mps" if torch.backends.mps.is_available() else
                      "cuda" if torch.cuda.is_available() else "cpu")
log.info(f"device = {device}")

# ---------- Model (skipped if TEST_PATTERN) ----------
if not TEST_PATTERN:
    log.info(f"loading MiDaS model = {MODEL_TYPE}")
    midas = torch.hub.load("intel-isl/MiDaS", MODEL_TYPE, trust_repo=True).to(device).eval()
    midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
    transform = midas_transforms.dpt_transform if MODEL_TYPE in ["DPT_Large", "DPT_Hybrid"] else midas_transforms.small_transform

# ---------- Camera ----------
cap = None
if not TEST_PATTERN:
    cap = cv2.VideoCapture(WEBCAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam index {WEBCAM_INDEX}")

def intrinsics(w, h, fov_deg):
    f = 0.5 * w / np.tan(np.deg2rad(fov_deg) / 2.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    return f, f, cx, cy

def normalize_depth(d):
    # Handle NaNs/Infs
    n_nan = np.count_nonzero(~np.isfinite(d))
    if n_nan:
        d = np.nan_to_num(d, nan=0.0, posinf=0.0, neginf=0.0)
    # Normalize to [0,1] and scale to pseudo-meters
    d = d - d.min()
    maxv = d.max()
    if maxv > 1e-6:
        d = d / maxv
    # map to [CLAMP_NEAR, CLAMP_FAR]
    return CLAMP_NEAR + (CLAMP_FAR - CLAMP_NEAR) * d

def make_test_pattern(t, w, h):
    """
    Generate a rotating slanted plane depth with simple color bands.
    Ensures client renders even if the camera/model is broken.
    """
    xx, yy = np.meshgrid(np.linspace(-1, 1, w, dtype=np.float32),
                         np.linspace(-1, 1, h, dtype=np.float32))
    angle = 0.6 * np.sin(t * 0.7)
    Z = 1.5 + 0.5 * (xx * np.cos(angle) + yy * np.sin(angle))
    Z = np.clip(Z, CLAMP_NEAR, CLAMP_FAR).astype(np.float32)
    # Color stripes
    r = (0.5 + 0.5 * np.sin(6.28 * xx + t)).astype(np.float32)
    g = (0.5 + 0.5 * np.sin(6.28 * yy + t*1.3)).astype(np.float32)
    b = (0.5 + 0.5 * np.sin(6.28 * (xx+yy) + t*0.9)).astype(np.float32)
    rgb = np.stack([r, g, b], axis=-1)  # h,w,3 in [0,1]
    rgb = (rgb * 255).astype(np.uint8).reshape(-1,3)
    return Z, rgb

ema_depth = None

# Stats
frame_count = 0
send_count = 0
last_log_t = time.time()

async def frame_stream(websocket):
    global ema_depth, frame_count, send_count, last_log_t

    log.info("client connected; starting stream loop")

    while True:
        t0 = time.time()

        if TEST_PATTERN:
            # Synthesize a frame at TARGET_WIDTH (scaled height ~ 16:9)
            w = TARGET_WIDTH
            h = int(TARGET_WIDTH * 9 / 16)
            d_norm, rgb = make_test_pattern(t0, w // STRIDE, h // STRIDE)
            # Already subsampled & clamped; build intrinsics
            hs, ws = d_norm.shape[:2]
            fx, fy, cx, cy = intrinsics(ws, hs, FOV_DEG)
        else:
            ok, frame = cap.read()
            if not ok:
                await asyncio.sleep(0.01)
                continue

            h0, w0 = frame.shape[:2]
            scale = TARGET_WIDTH / float(w0)
            w = int(w0 * scale); h = int(h0 * scale)
            frame_s = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            rgb_full = cv2.cvtColor(frame_s, cv2.COLOR_BGR2RGB)

            # Depth inference
            with torch.no_grad():
                inp = transform(rgb_full).to(device, dtype=torch.float32)
                pred = midas(inp)                               # [H',W'] -> logits
                depth = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=(h, w),
                    mode="bicubic", align_corners=False
                ).squeeze().cpu().numpy()

            d_norm = normalize_depth(depth)
            # EMA smoothing
            ema_depth = d_norm if ema_depth is None else (EMA_ALPHA * d_norm + (1.0 - EMA_ALPHA) * ema_depth)

            # Subsample for bandwidth
            d_norm = ema_depth[::STRIDE, ::STRIDE].astype(np.float32, copy=False)
            rgb = rgb_full[::STRIDE, ::STRIDE].reshape(-1, 3).astype(np.uint8, copy=False)
            hs, ws = d_norm.shape[:2]
            fx, fy, cx, cy = intrinsics(ws, hs, FOV_DEG)

        # Header
        header = {
            "w": int(ws), "h": int(hs),
            "fx": float(fx), "fy": float(fy),
            "cx": float(cx), "cy": float(cy),
            "stride": int(STRIDE),
            "ts": t0
        }
        header_bytes = json.dumps(header).encode("utf-8")
        header_len = struct.pack("<I", len(header_bytes))
        pad = (4 - (len(header_bytes) & 3)) & 3
        pad_bytes = b"\x00" * pad

        # Payload
        depth_bytes = d_norm.astype(np.float32, copy=False).tobytes(order="C")
        rgb_bytes = rgb.tobytes(order="C")

        blob = b"".join([header_len, header_bytes, pad_bytes, depth_bytes, rgb_bytes])

        # Send
        try:
            await websocket.send(blob)
            send_count += 1
        except Exception as e:
            log.warning(f"websocket send failed: {e}")
            break

        frame_count += 1

        # Periodic log
        now = time.time()
        if now - last_log_t >= LOG_EVERY_SEC:
            size_kb = len(blob) / 1024.0
            dmin = float(np.min(d_norm)) if d_norm.size else -1
            dmax = float(np.max(d_norm)) if d_norm.size else -1
            dmean = float(np.mean(d_norm)) if d_norm.size else -1
            log.info(
                f"frames={frame_count} sent={send_count} | "
                f"grid={ws}x{hs} N={ws*hs} | blob={size_kb:.1f} KB | "
                f"depth[min/mean/max]={dmin:.3f}/{dmean:.3f}/{dmax:.3f}"
            )
            last_log_t = now

        # Keep the loop cooperative
        await asyncio.sleep(0)

async def handler(websocket):
    # Send a hello frame (just 4 bytes for header length == 0)
    await websocket.send(struct.pack("<I", 0))
    await frame_stream(websocket)

async def main():
    async with websockets.serve(handler, "localhost", PORT, max_size=None, ping_interval=20):
        log.info(f"Streaming on ws://localhost:{PORT} | TEST_PATTERN={int(TEST_PATTERN)} | stride={STRIDE}")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if cap is not None:
            cap.release()
