import sys, os, subprocess, webbrowser, time, signal
from pathlib import Path

script_dir = Path(__file__).parent
cloudflared = Path(os.environ["LOCALAPPDATA"]) / "cloudflared" / "cloudflared.exe"
port = 5000

os.system("cls" if os.name == "nt" else "clear")
print("=" * 55)
print("  Crypto Smart Money Tracker — Go Online")
print("  (via Cloudflare Tunnel)")
print("=" * 55)

# Start Flask if not running
flask = None
try:
    import urllib.request
    urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=2)
    print("  [OK] Flask already running")
except:
    print("  [..] Starting Flask...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    flask = subprocess.Popen([sys.executable, str(script_dir / "web" / "app.py")], cwd=script_dir / "web", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    print("  [OK] Flask started")

# Start cloudflared tunnel
print("  [..] Starting Cloudflare Tunnel...")
proc = subprocess.Popen(
    [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{port}"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
)

url = None
start = time.time()
while time.time() - start < 30:
    line = proc.stdout.readline()
    if not line:
        time.sleep(0.1)
        continue
    print(f"     {line.rstrip()}")
    if "trycloudflare.com" in line and "https://" in line:
        for w in line.split():
            if "trycloudflare.com" in w:
                url = w.strip()
                break
    if url:
        break

if not url:
    rem = proc.stdout.read(500)
    print(rem)
    print("\n  [ERROR] Could not get tunnel URL")
    proc.kill()
    sys.exit(1)

print(f"\n  {'='*55}")
print(f"  PUBLIC URL:  {url}")
print(f"  {'='*55}")
print(f"  Share this link! (Ctrl+C to stop)\n")

webbrowser.open(url)

def cleanup(*a):
    print("\n  Closing...")
    proc.kill()
    if flask: flask.kill()
    exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

try:
    while True:
        line = proc.stdout.readline()
        if line: print(f"     {line.rstrip()}")
        time.sleep(0.1)
except KeyboardInterrupt:
    cleanup()
