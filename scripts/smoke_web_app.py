"""CI-only HTTP smoke test: boot Shiny and verify the real page is served."""
from __future__ import annotations
import subprocess
import sys
import time
from urllib.request import urlopen


def main() -> None:
    cmd = [sys.executable, "-m", "shiny", "run", "--host", "127.0.0.1",
           "--port", "8771", "app.py"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        last_error = None
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError(f"Shiny process exited with status {process.returncode}")
            try:
                with urlopen("http://127.0.0.1:8771/", timeout=2) as response:
                    html = response.read().decode("utf-8")
                    if response.status != 200 or "Flux Capacitor" not in html:
                        raise RuntimeError("Shiny response missing Flux Capacitor app")
                    print("Shiny HTTP smoke test passed: root page served.")
                    return
            except OSError as exc:
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError(f"Shiny did not serve page: {last_error}")
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)


if __name__ == "__main__":
    main()
