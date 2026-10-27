"""SmartHeal process watchdog: restart the Flask child after a crash or repeated failed health checks."""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_FILE = os.path.join(BASE_DIR, "app.py")
HEALTH_URL = os.environ.get("SMARTHEAL_HEALTH_URL", "http://127.0.0.1:5000/api/health")
CHECK_INTERVAL = float(os.environ.get("WATCHDOG_INTERVAL", "3"))
FAILURE_LIMIT = int(os.environ.get("WATCHDOG_FAILURE_LIMIT", "3"))
RESTART_DELAY = float(os.environ.get("WATCHDOG_RESTART_DELAY", "2"))
LOG_FILE = os.path.join(BASE_DIR, "watchdog.log")


def log(message):
    line = f"{datetime.now().isoformat(timespec='seconds')} | {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(line + "\n")


def healthy():
    try:
        request = urllib.request.Request(HEALTH_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main():
    log("SmartHeal watchdog started. Press Ctrl+C to stop the watchdog and app.")
    child = None
    failures = 0
    try:
        while True:
            if child is None or child.poll() is not None:
                if child is not None:
                    log(f"App process exited with code {child.returncode}; restarting automatically.")
                child = subprocess.Popen([sys.executable, APP_FILE], cwd=BASE_DIR)
                log(f"Started app process PID={child.pid}.")
                failures = 0
                time.sleep(2)

            if healthy():
                failures = 0
            else:
                failures += 1
                log(f"Health check failed ({failures}/{FAILURE_LIMIT}).")
                if failures >= FAILURE_LIMIT:
                    log("App is unresponsive; terminating child so it can be restarted.")
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
                    child = None
                    failures = 0
                    time.sleep(RESTART_DELAY)
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        log("Watchdog stopping by user request.")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        log("Watchdog stopped.")


if __name__ == "__main__":
    main()
