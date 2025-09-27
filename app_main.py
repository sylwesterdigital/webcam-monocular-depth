# app_main.py
import os, sys, time, socket, threading, webbrowser, asyncio, ssl, http.server, socketserver
from pathlib import Path

# --- capture app-level stdout/stderr into same log file ---
def _redirect_stdio_to_log():
    logdir = os.path.expanduser("~/Library/Logs/LiveDepth")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "LiveDepth.log")
    f = open(logfile, "a", buffering=1)
    sys.stdout = f
    sys.stderr = f
    print("[LiveDepth] stdio ->", logfile)
_redirect_stdio_to_log()


HTTPS_PORT = int(os.getenv("HTTPS_PORT", "8443"))
WSS_PORT   = int(os.getenv("PORT", "8765"))  # keep in sync with server.py
CERT_PATH  = os.getenv("HTTPS_CERT_PATH", "certs/localhost+2.pem")
KEY_PATH   = os.getenv("HTTPS_KEY_PATH",  "certs/localhost+2-key.pem")

# Optional: version strings (set by build script or spec); used by About panel
APP_VERSION  = os.getenv("APP_VERSION", "0.1.0")   # marketing version
BUILD_NUMBER = os.getenv("BUILD_NUMBER", "1")      # build number (integer-like)

# ---- Paths inside PyInstaller bundle or source tree ----
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
CLIENT_DIR = BASE / "client"               # bundled client
CERT_FILE = BASE / CERT_PATH               # bundled certs
KEY_FILE  = BASE / KEY_PATH

# ---- Server thread (model/camera + WSS) ----
def _run_wss():
    # Ensure server.py sees the right paths/ports
    os.environ.setdefault("PORT", str(WSS_PORT))
    os.environ.setdefault("HTTPS_CERT_PATH", str(CERT_FILE))
    os.environ.setdefault("HTTPS_KEY_PATH",  str(KEY_FILE))
    import server
    asyncio.run(server.main())

# ---- HTTPS static file server (serves client/) ----
class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    # silence noisy logs
    def log_message(self, fmt, *args): pass

def _run_https_static():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))

    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(CLIENT_DIR), **kw)
    with socketserver.TCPServer(("127.0.0.1", HTTPS_PORT), handler, bind_and_activate=False) as httpd:
        httpd.allow_reuse_address = True
        httpd.server_bind()
        httpd.server_activate()
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        httpd.serve_forever()

def _wait_for_port(host, port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False

def _open_browser():
    url = f"https://127.0.0.1:{HTTPS_PORT}/?port={WSS_PORT}"
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        os.system(f'open "{url}"')

# ---- Menu-bar status item (Cocoa) ----
from Cocoa import (
    NSApp, NSApplication, NSApplicationActivationPolicyAccessory,
    NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength
)
# About panel options live in AppKit; import the constants explicitly
from AppKit import (
    NSAboutPanelOptionApplicationName,
    NSAboutPanelOptionApplicationVersion,
    NSAboutPanelOptionVersion,
    NSAboutPanelOptionCredits,
)
import PyObjCTools.AppHelper as AppHelper
from Foundation import NSObject, NSDictionary, NSAttributedString

class AppDelegate(NSObject):
    def openViewer_(self, _): _open_browser()

    def restartServer_(self, _):
        global _wss_thread
        try:
            _wss_thread = threading.Thread(target=_run_wss, name="DepthWSS", daemon=True)
            _wss_thread.start()
        except Exception as e:
            print("[LiveDepth] restart failed:", e, file=sys.stderr)

    # --- About panel handler (shows standard macOS About window) ---
    def about_(self, _):
        # credits can be plain or attributed text
        credits = NSAttributedString.alloc().initWithString_(
            "LiveDepth — Monocular depth streaming demo\n"
            "© 2025 Sylwester Mielniczuk — WORKWORK.FUN LTD (UK)"
        )
        opts = {
            NSAboutPanelOptionApplicationName: "LiveDepth",
            NSAboutPanelOptionApplicationVersion: APP_VERSION,   # big version text
            NSAboutPanelOptionVersion: f"Build {BUILD_NUMBER}",  # small line under it
            NSAboutPanelOptionCredits: credits,
        }
        NSApp.activateIgnoringOtherApps_(True)
        NSApp.orderFrontStandardAboutPanelWithOptions_(NSDictionary.dictionaryWithDictionary_(opts))

    def quit_(self, _): os._exit(0)

def _run_statusbar_ui():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    statusbar = NSStatusBar.systemStatusBar()
    item = statusbar.statusItemWithLength_(NSVariableStatusItemLength)
    item.button().setTitle_("LiveDepth")
    menu = NSMenu.alloc().init()
    delegate = AppDelegate.alloc().init()

    # --- About menu item (opens standard About panel) ---
    mi_about = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("About LiveDepth", "about:", "")
    mi_about.setTarget_(delegate); menu.addItem_(mi_about)

    mi_open = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open Viewer", "openViewer:", "")
    mi_open.setTarget_(delegate); menu.addItem_(mi_open)
    mi_restart = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Restart Server", "restartServer:", "")
    mi_restart.setTarget_(delegate); menu.addItem_(mi_restart)
    menu.addItem_(NSMenuItem.separatorItem())
    mi_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit LiveDepth", "quit:", "q")
    mi_quit.setTarget_(delegate); menu.addItem_(mi_quit)
    item.setMenu_(menu)

    # Start HTTPS static and WSS servers
    global _https_thread, _wss_thread
    _https_thread = threading.Thread(target=_run_https_static, name="HTTPS-Static", daemon=True)
    _https_thread.start()

    _wss_thread = threading.Thread(target=_run_wss, name="DepthWSS", daemon=True)
    _wss_thread.start()

    # Wait for HTTPS to be ready then open the page
    if _wait_for_port("127.0.0.1", HTTPS_PORT, 10):
        _open_browser()

    AppHelper.runEventLoop()

def main():
    # fail-fast if certs missing
    if not (CERT_FILE.exists() and KEY_FILE.exists()):
        print(f"[LiveDepth] Missing cert files:\n  {CERT_FILE}\n  {KEY_FILE}", file=sys.stderr)
        os._exit(2)
    _run_statusbar_ui()

if __name__ == "__main__":
    main()
