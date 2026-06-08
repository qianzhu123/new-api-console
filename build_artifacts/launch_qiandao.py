#!/usr/bin/env python3
"""Lightweight launcher for the qiandao local web console.

The generated executable is intended to live in the project root directory.
It mirrors run_web.bat: stop the old service on port 5050, open the browser,
and start `python app.py`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORT = 5050
URL = f"http://127.0.0.1:{PORT}"


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Source file is stored in build_artifacts during development.
    return Path(__file__).resolve().parent.parent


def find_python() -> str | None:
    candidates = ["python", "py"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return candidate
    return None


def stop_port_listener(port: int) -> None:
    ps = (
        "$attempt = 0; "
        f"while ($attempt -lt 20) {{ "
        f"$processIds = @(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess -Unique); "
        "if ($processIds.Count -eq 0) { exit 0 }; "
        "foreach ($processId in $processIds) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }; "
        "Start-Sleep -Milliseconds 250; $attempt++ "
        "}; "
        f"Write-Error 'Port {port} is still in use after stopping previous services.'; exit 1"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
    )


def main() -> int:
    project_root = get_project_root()
    app_py = project_root / "app.py"

    print(f"Project root: {project_root}")
    if not app_py.exists():
        print(f"ERROR: app.py was not found at: {app_py}", file=sys.stderr)
        input("Press Enter to exit...")
        return 1

    python_cmd = find_python()
    if not python_cmd:
        print("ERROR: Python is not found in PATH.", file=sys.stderr)
        input("Press Enter to exit...")
        return 1

    print(f"Stopping the previous service on port {PORT} ...")
    try:
        stop_port_listener(PORT)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: failed to stop the previous service: {exc}", file=sys.stderr)
        input("Press Enter to exit...")
        return exc.returncode or 1

    print(f"Starting qiandao Local Web Console on {URL} ...")
    # Give the process a tiny moment to start before the browser navigates.
    try:
        webbrowser.open(URL)
    except Exception as exc:  # Browser opening failure should not block the server.
        print(f"WARNING: failed to open browser automatically: {exc}")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    try:
        proc = subprocess.Popen([python_cmd, str(app_py)], cwd=str(project_root), env=env)
        return proc.wait()
    except KeyboardInterrupt:
        print("\nStopping service ...")
        try:
            proc.terminate()  # type: ignore[name-defined]
            time.sleep(1)
        except Exception:
            pass
        return 130
    except Exception as exc:
        print(f"ERROR: failed to start app.py: {exc}", file=sys.stderr)
        input("Press Enter to exit...")
        return 1
    finally:
        print("Launcher exited.")


if __name__ == "__main__":
    raise SystemExit(main())
