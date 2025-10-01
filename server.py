#!/usr/bin/env python3
# macOS / Python 3.10+ recommended
# pip install opencv-python torch torchvision torchaudio pillow websockets numpy timm

import asyncio, struct, json, time, os, logging, subprocess, sys, re, shutil, socket, ssl
import cv2
import numpy as np
import torch
import websockets

# --- logging to file in ~/Library/Logs/LiveDepth ---
from logging.handlers import RotatingFileHandler
def _setup_file_logging():
    logdir = os.path.expanduser("~/Library/Logs/LiveDepth")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "LiveDepth.log")
    fh = RotatingFileHandler(logfile, maxBytes=5_000_000, backupCount=3)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    fh.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    logging.getLogger().addHandler(fh)
    logging.getLogger("depth-stream").info(f"log file: {logfile}")
_setup_file_logging()

# ------------------------ config ------------------------
WEBCAM_INDEX = int(os.getenv("WEBCAM_INDEX", "0"))
WEBCAM_NAME  = os.getenv("WEBCAM_NAME", "").strip()  # optional, macOS AVFoundation name (e.g. 'FaceTime HD Camera')
TARGET_WIDTH = int(os.getenv("TARGET_WIDTH", "640"))
STRIDE       = int(os.getenv("STRIDE", "2"))         # 1=full res; 2/3 reduces payload
FOV_DEG      = float(os.getenv("FOV_DEG", "60.0"))
PORT         = int(os.getenv("PORT", "8765"))
#BIND_HOST    = os.getenv("BIND_HOST", "localhost")   # <— no hardcoded IP; matches page host
BIND_HOST    = os.getenv("BIND_HOST", "0.0.0.0")


MODEL_TYPE   = os.getenv("MODEL_TYPE", "MiDaS_small")# "MiDaS_small" | "DPT_Large" | "DPT_Hybrid"
#MODEL_TYPE   = os.getenv("MODEL_TYPE", "DPT_Hybrid")# "MiDaS_small" | "DPT_Large" | "DPT_Hybrid"
#MODEL_TYPE   = os.getenv("MODEL_TYPE", "DPT_Large")# "MiDaS_small" | "DPT_Large" | "DPT_Hybrid"

EMA_ALPHA    = float(os.getenv("EMA_ALPHA", "0.2"))
CLAMP_NEAR   = float(os.getenv("CLAMP_NEAR", "0.2"))
CLAMP_FAR    = float(os.getenv("CLAMP_FAR",  "1.0"))

TEST_PATTERN = bool(int(os.getenv("TEST_PATTERN", "0")))  # 1 = synthetic pattern
LOG_EVERY_SEC= float(os.getenv("LOG_EVERY_SEC", "2.0"))

LOG_LEVEL    = os.getenv("LOG_LEVEL", "INFO").upper()

# TLS
USE_TLS          = int(os.getenv("USE_TLS", "1"))     # 1 = WSS (default), 0 = WS
HTTPS_CERT_PATH  = os.getenv("HTTPS_CERT_PATH", "certs/localhost+2.pem")
HTTPS_KEY_PATH   = os.getenv("HTTPS_KEY_PATH",  "certs/localhost+2-key.pem")

# WebSocket keepalive (tweakable)
PING_INTERVAL = float(os.getenv("PING_INTERVAL", "20"))
PING_TIMEOUT  = float(os.getenv("PING_TIMEOUT",  "20"))
# --------------------------------------------------------

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("depth-stream")

device = torch.device("mps" if torch.backends.mps.is_available() else
                      "cuda" if torch.cuda.is_available() else "cpu")
log.info(f"device = {device}")

def intrinsics(w, h, fov_deg):
    f = 0.5 * w / np.tan(np.deg2rad(fov_deg) / 2.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    return f, f, cx, cy

def normalize_depth(d):
    if not np.isfinite(d).all():
        d = np.nan_to_num(d, nan=0.0, posinf=0.0, neginf=0.0)
    d = d - np.min(d)
    maxv = float(np.max(d))
    if maxv > 1e-6:
        d = d / maxv
    return CLAMP_NEAR + (CLAMP_FAR - CLAMP_NEAR) * d

def make_test_pattern(t, w, h):
    xx, yy = np.meshgrid(np.linspace(-1, 1, w, dtype=np.float32),
                         np.linspace(-1, 1, h, dtype=np.float32))
    angle = 0.6 * np.sin(t * 0.7)
    Z = 1.5 + 0.5 * (xx * np.cos(angle) + yy * np.sin(angle))
    Z = np.clip(Z, CLAMP_NEAR, CLAMP_FAR).astype(np.float32)
    r = (0.5 + 0.5 * np.sin(6.28 * xx + t)).astype(np.float32)
    g = (0.5 + 0.5 * np.sin(6.28 * yy + t*1.3)).astype(np.float32)
    b = (0.5 + 0.5 * np.sin(6.28 * (xx+yy) + t*0.9)).astype(np.float32)
    rgb = np.stack([r, g, b], axis=-1)
    rgb = (rgb * 255).astype(np.uint8).reshape(-1,3)
    return Z, rgb

def ffmpeg_path():
    return shutil.which("ffmpeg")

def enumerate_avfoundation_devices():
    """macOS: returns list of (index:int, name:str) for AVFoundation video devices. Requires ffmpeg."""
    if sys.platform != "darwin":
        return []
    ff = ffmpeg_path()
    if not ff:
        return []
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, text=True
        )
        out = proc.stdout
        devices = []
        for line in out.splitlines():
            m = re.search(r"\[AVFoundation indev .*?\]\s*\[(\d+)\]\s*(.+)", line)
            if m and "video devices" not in line.lower() and "audio devices" not in line.lower():
                idx = int(m.group(1))
                name = m.group(2).strip()
                if not name.lower().startswith("capture screen"):
                    devices.append((idx, name))
        return devices
    except Exception as e:
        log.warning(f"ffmpeg enumerate failed: {e}")
        return []

def enumerate_cv2_guess(max_index=8):
    """Fallback when ffmpeg listing isn't available."""
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            found.append((i, f"Camera {i}"))
        cap.release()
    return found

def resolve_webcam_index(name_pref: str, fallback_index: int) -> int:
    name_pref = (name_pref or "").strip()
    if not name_pref:
        return fallback_index
    devs = enumerate_avfoundation_devices()
    if not devs:
        log.warning("No AVFoundation device listing. Falling back to WEBCAM_INDEX.")
        return fallback_index
    for idx, nm in devs:
        if nm == name_pref:
            log.info(f"WEBCAM_NAME='{name_pref}' -> index {idx}")
            return idx
    name_l = name_pref.lower()
    for idx, nm in devs:
        if name_l in nm.lower():
            log.info(f"WEBCAM_NAME~='{name_pref}' matched '{nm}' -> index {idx}")
            return idx
    log.warning(f"WEBCAM_NAME='{name_pref}' not found. Using WEBCAM_INDEX={fallback_index}.")
    return fallback_index


def _clamp_params(ema, near_, far_):
    # guardrails and defaults
    ema  = float(ema)  if ema  is not None else EMA_ALPHA
    near_= float(near_) if near_ is not None else CLAMP_NEAR
    far_ = float(far_)  if far_  is not None else CLAMP_FAR
    # fix ordering if needed
    if far_ <= near_:
        far_ = near_ + 1e-3
    # bounds you like (optional)
    ema   = max(0.0, min(1.0, ema))
    near_ = max(0.0, near_)
    far_  = max(near_ + 1e-3, far_)
    return ema, near_, far_



# ---------- Model (skipped if TEST_PATTERN) ----------
if not TEST_PATTERN:
    log.info(f"loading MiDaS model = {MODEL_TYPE}")
    midas = torch.hub.load("intel-isl/MiDaS", MODEL_TYPE, trust_repo=True).to(device).eval()
    midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
    transform = midas_transforms.dpt_transform if MODEL_TYPE in ["DPT_Large", "DPT_Hybrid"] else midas_transforms.small_transform

# ---------- Camera open/switch ----------
cap = None
resolved_index = WEBCAM_INDEX

def open_camera(index: int):
    global cap, resolved_index
    if cap is not None:
        try: cap.release()
        except: pass
    c = cv2.VideoCapture(index)
    c.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not c.isOpened():
        raise RuntimeError(f"Cannot open webcam index {index}")
    cap = c
    resolved_index = index
    log.info(f"Opened camera index {index}")

if not TEST_PATTERN:
    resolved_index = resolve_webcam_index(WEBCAM_NAME, WEBCAM_INDEX)
    try:
        open_camera(resolved_index)
    except Exception as e:
        log.error("Camera open failed: %r", e)

ema_depth = None
frame_count = 0
send_count = 0
last_log_t = time.time()

# --- hardened frame loop (never kills the socket on transient errors) ---
async def frame_stream(websocket):
    """Producer: stream frames to the connected client, never crash the connection."""
    global ema_depth, frame_count, send_count, last_log_t
    peer = getattr(websocket, "remote_address", None)
    log.info("client connected: %s", peer)

    use_test_fallback = TEST_PATTERN  # if we hit an error, flip to synthetic temporarily

    while True:
        try:
            t0 = time.time()

            if use_test_fallback:
                w = TARGET_WIDTH
                h = int(TARGET_WIDTH * 9 / 16)
                d_norm, rgb = make_test_pattern(t0, w // STRIDE, h // STRIDE)
                hs, ws = d_norm.shape[:2]
                fx, fy, cx, cy = intrinsics(ws, hs, FOV_DEG)
            else:
                if cap is None:
                    await asyncio.sleep(0.03)
                    continue

                ok, frame = cap.read()
                if not ok:
                    await asyncio.sleep(0.01)
                    continue

                h0, w0 = frame.shape[:2]
                scale = TARGET_WIDTH / float(w0)
                w = int(w0 * scale); h = int(h0 * scale)
                frame_s = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                rgb_full = cv2.cvtColor(frame_s, cv2.COLOR_BGR2RGB)

                with torch.no_grad():
                    inp  = transform(rgb_full).to(device, dtype=torch.float32)
                    pred = midas(inp)
                    depth = torch.nn.functional.interpolate(
                        pred.unsqueeze(1), size=(h, w),
                        mode="bicubic", align_corners=False
                    ).squeeze().cpu().numpy()

                d_norm = normalize_depth(depth)
                ema_depth = d_norm if ema_depth is None else (EMA_ALPHA * d_norm + (1.0 - EMA_ALPHA) * ema_depth)

                d_norm = ema_depth[::STRIDE, ::STRIDE].astype(np.float32, copy=False)
                rgb    = rgb_full[::STRIDE, ::STRIDE].reshape(-1, 3).astype(np.uint8, copy=False)
                hs, ws = d_norm.shape[:2]
                fx, fy, cx, cy = intrinsics(ws, hs, FOV_DEG)

            header = {
                "w": int(ws), "h": int(hs),
                "fx": float(fx), "fy": float(fy),
                "cx": float(cx), "cy": float(cy),
                "stride": int(STRIDE),
                "ts": t0
            }
            header_bytes = json.dumps(header).encode("utf-8")
            header_len   = struct.pack("<I", len(header_bytes))
            pad          = (4 - (len(header_bytes) & 3)) & 3
            pad_bytes    = b"\x00" * pad

            depth_bytes = d_norm.astype(np.float32, copy=False).tobytes(order="C")
            rgb_bytes   = rgb.tobytes(order="C")
            blob        = b"".join([header_len, header_bytes, pad_bytes, depth_bytes, rgb_bytes])

            await websocket.send(blob)
            send_count += 1
            frame_count += 1

            if use_test_fallback and not TEST_PATTERN:
                use_test_fallback = False  # probe back to real path

            now = time.time()
            if now - last_log_t >= LOG_EVERY_SEC:
                size_kb = len(blob) / 1024.0
                dmin = float(np.min(d_norm)) if d_norm.size else -1
                dmax = float(np.max(d_norm)) if d_norm.size else -1
                dmean = float(np.mean(d_norm)) if d_norm.size else -1
                log.info(f"frames={frame_count} sent={send_count} | grid={ws}x{hs} N={ws*hs} | blob={size_kb:.1f} KB | depth[min/mean/max]={dmin:.3f}/{dmean:.3f}/{dmax:.3f}")
                last_log_t = now

            await asyncio.sleep(0)

        except websockets.ConnectionClosed:
            log.info("client disconnected: %s", peer)
            break
        except Exception as e:
            log.exception("frame loop error (falling back to TEST_PATTERN): %r", e)
            use_test_fallback = True
            await asyncio.sleep(0.05)

async def send_json(ws, obj):
    try:
        await ws.send(json.dumps(obj))
    except Exception as e:
        log.warning(f"send_json failed: {e}")

def camera_listing():
    av = enumerate_avfoundation_devices()
    items = av if av else enumerate_cv2_guess(8)
    return [{"index": i, "name": n} for i, n in items]

async def control_loop(ws):
    """Consumer: handle JSON control messages."""
    async for msg in ws:
        if isinstance(msg, (bytes, bytearray)):
            continue
        try:
            data = json.loads(msg)
        except Exception:
            continue

        cmd = data.get("cmd")
        if cmd == "list_cams":
            await send_json(ws, {"type":"cams","items":camera_listing(),"selected":resolved_index})
        elif cmd == "set_cam":
            idx = int(data.get("index", resolved_index))
            try:
                if not TEST_PATTERN:
                    open_camera(idx)
                await send_json(ws, {"type":"set_cam_ok","index":idx})
            except Exception as e:
                await send_json(ws, {"type":"set_cam_err","error":str(e)})

        # --- NEW: live server params ---
        elif cmd == "get_params":
            await send_current_params(ws)

        elif cmd == "set_params":
            global EMA_ALPHA, CLAMP_NEAR, CLAMP_FAR
            try:
                ema  = data.get("ema_alpha", None)
                near_= data.get("clamp_near", None)
                far_ = data.get("clamp_far",  None)
                ema, near_, far_ = _clamp_params(ema, near_, far_)
                EMA_ALPHA  = ema
                CLAMP_NEAR = near_
                CLAMP_FAR  = far_
                await send_json(ws, {
                    "type":"params_ok",
                    "ema_alpha": EMA_ALPHA,
                    "clamp_near": CLAMP_NEAR,
                    "clamp_far": CLAMP_FAR
                })
            except Exception as e:
                await send_json(ws, {"type":"params_err","error":str(e)})



async def send_current_params(ws):
    await send_json(ws, {
        "type": "params",
        "ema_alpha": EMA_ALPHA,
        "clamp_near": CLAMP_NEAR,
        "clamp_far": CLAMP_FAR
    })

async def handler(websocket):
    # hello (header length == 0)
    await websocket.send(struct.pack("<I", 0))
    await send_current_params(websocket)
    producer = asyncio.create_task(frame_stream(websocket))
    consumer = asyncio.create_task(control_loop(websocket))
    done, pending = await asyncio.wait({producer, consumer}, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()

def build_ssl_context():
    """Return SSL context if USE_TLS=1; otherwise None."""
    if not USE_TLS:
        log.warning("TLS disabled (USE_TLS=0) — serving plain ws://")
        return None
    cert_file = HTTPS_CERT_PATH
    key_file  = HTTPS_KEY_PATH
    if not (os.path.exists(cert_file) and os.path.exists(key_file)):
        raise FileNotFoundError(
            f"TLS enabled but cert/key not found:\n  cert={cert_file}\n  key={key_file}\n"
            f"Set HTTPS_CERT_PATH / HTTPS_KEY_PATH or USE_TLS=0."
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return ctx

async def main():
    # Ensure bind host is reachable (helpful log)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((BIND_HOST, 0)); s.close()
    except Exception:
        log.warning(f"BIND_HOST '{BIND_HOST}' may not be reachable")

    ssl_context = build_ssl_context()
    scheme = "wss" if ssl_context else "ws"

    # IMPORTANT: pass ssl=ssl_context to enable WSS
    async with websockets.serve(
        handler,
        BIND_HOST,
        PORT,
        max_size=None,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        ssl=ssl_context,
        process_request=None,
        origins=None  # allow all localhost/dev origins
    ):
        log.info(f"Streaming on {scheme}://{BIND_HOST}:{PORT} | TEST_PATTERN={int(TEST_PATTERN)} | stride={STRIDE} | cam_index={resolved_index} name='{WEBCAM_NAME}'")
        if ssl_context:
            log.info(f"TLS cert: {HTTPS_CERT_PATH}")
            log.info(f"TLS key : {HTTPS_KEY_PATH}")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        try:
            if 'cap' in globals() and cap is not None:
                cap.release()
        except:
            pass
