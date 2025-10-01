# LiveDepth.spec — macOS app bundle (.app)
# Build with:  pyinstaller LiveDepth.spec --noconfirm
#
# If you keep models in ./weights they’ll be bundled. Remove that tuple if unused.

import os, time
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules  # <-- added collect_submodules

# --- Local versioning (no Git, no env) ---
# Uses a persistent counter file to bump build every time you run PyInstaller.
# You can change BASE_VERSION whenever you want; the counter keeps incrementing.
BASE_VERSION = os.getenv("APP_VERSION_BASE", "0.9.0-beta")   # your marketing base (change when you want)
COUNTER_FILE = Path("build/.app_build_counter")               # persists across builds

def _read_int(p: Path) -> int:
    try:
        with p.open("r", encoding="utf-8") as f:
            return int((f.read().strip() or "0"))
    except Exception:
        return 0

def _atomic_write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)

def bump_build_counter() -> int:
    n = _read_int(COUNTER_FILE) + 1
    _atomic_write(COUNTER_FILE, str(n))
    return n

BUILD_COUNTER = bump_build_counter()                     # 1,2,3,…
APP_VERSION   = f"{BASE_VERSION}.{BUILD_COUNTER}"        # e.g. "0.9.0-beta.17"
BUILD_NUMBER  = str(BUILD_COUNTER)                       # CFBundleVersion must be numeric (string)

# Optional: reset via env once (e.g. APP_RESET_COUNTER=100)
_reset = os.getenv("APP_RESET_COUNTER")
if _reset and _reset.isdigit():
    _atomic_write(COUNTER_FILE, _reset)
    BUILD_COUNTER = int(_reset)
    APP_VERSION   = f"{BASE_VERSION}.{BUILD_COUNTER}"
    BUILD_NUMBER  = str(BUILD_COUNTER)
# -----------------------------------------


# --- Explicit project data you want inside the .app bundle ---
datas = [
    ('client', 'client'),
    ('weights', 'weights'),
    ('certs',   'certs'),     # <— add this line
]

binaries = []
hiddenimports = ['timm', 'timm.layers', 'torchvision.ops']

# --- Pull in third-party package resources comprehensively ---
for pkg in ('torch', 'torchvision', 'timm', 'cv2'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# --- Minimal fix for bundled crash: include torch.distributed submodules ---
hiddenimports += collect_submodules("torch.distributed")   # <-- single crucial addition

# --- Standard PyInstaller pipeline ---
a = Analysis(
    ['app_main.py'],          # your entry point (starts server, opens client)
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,    # binaries go into COLLECT so the .app has them
    name='LiveDepth',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX is unnecessary/risky on macOS
    console=False,            # windowed app (no terminal window)
    disable_windowed_traceback=False,
    argv_emulation=False,     # set True only if you need Finder drag&drop args
    target_arch=None,
    codesign_identity=None,   # you can fill this for codesigning later
    entitlements_file=None,   # or add a custom entitlements plist here
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LiveDepth',
)

# --- Wrap into a proper macOS .app and add Info.plist keys (camera prompt) ---

# LiveDepth.spec — replace your BUNDLE(...) with this:
app = BUNDLE(
    coll,
    name='LiveDepth.app',
    icon='assets/LiveDepth.icns',  # <— use your generated ICNS
    bundle_identifier='com.yourdomain.livedepth',
    info_plist={
        # Required for camera prompt
        "NSCameraUsageDescription": "LiveDepth needs camera access to compute monocular depth in real time.",

        # ---- versioning (local counter) ----
        "CFBundleShortVersionString": APP_VERSION,   # marketing version (e.g. 0.9.0-beta.17)
        "CFBundleVersion": BUILD_NUMBER,             # numeric build as string (e.g. "17")

        # (optional) QoL keys
        "LSMinimumSystemVersion": "11.0",            # require Big Sur+
        "NSHighResolutionCapable": True,             # retina rendering

        # (optional) About panel / credits
        # "LSApplicationCategoryType": "public.app-category.graphics-design",
        # Shown in Finder “Get Info” and About window:
        "NSHumanReadableCopyright": "© 2025 Sylwester Mielniczuk. WORKWORK.FUN LTD, UK. All rights reserved.",
        # Leave LSUIElement out here (we set Accessory policy in code)
    },
)
