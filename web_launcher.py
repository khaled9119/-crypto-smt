import subprocess, sys, os, webbrowser, time
from pathlib import Path

script_dir = Path(__file__).parent
web_app = script_dir / "web" / "app.py"

os.system("cls" if os.name == "nt" else "clear")
print("=" * 52)
print("  Crypto Smart Money Tracker Pro - Web UI")
print("=" * 52)
print("  Starting server (waitress)...")

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

proc = subprocess.Popen([sys.executable, str(web_app)], cwd=script_dir / "web",
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

time.sleep(3)
webbrowser.open("http://localhost:5000")
print("  [OK] http://localhost:5000")
print("=" * 52)
print("  Close this window to stop.")
print()

try:
    for line in iter(proc.stdout.readline, b""):
        if line:
            print(line.decode("utf-8", errors="replace").rstrip())
except KeyboardInterrupt:
    proc.terminate()
    print("\n  Stopped.")
