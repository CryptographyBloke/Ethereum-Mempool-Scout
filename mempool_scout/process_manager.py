"""Railway all-in-one process manager; preserve Docker Compose subcommands."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if args != ["all"]:
        os.execvp("mempool-scout", ["mempool-scout", *args])

    wss_url = os.environ.get("SCOUT_WSS_URL", "").strip()
    if not wss_url.startswith(("wss://", "ws://")):
        print("SCOUT_WSS_URL must be a WebSocket Ethereum RPC URL", file=sys.stderr)
        return 2

    port = os.environ.get("PORT", "8000")
    if not port.isascii() or not port.isdecimal() or not (1 <= int(port) <= 65535):
        print("PORT must be a TCP port (1-65535)", file=sys.stderr)
        return 2

    fetch_mode = os.environ.get("SCOUT_FETCH_MODE", "full")
    if fetch_mode not in ("full", "hash"):
        print("SCOUT_FETCH_MODE must be full or hash", file=sys.stderr)
        return 2

    db_path = os.environ.get("SCOUT_DB", "/data/scout.sqlite")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("RAILWAY_PROJECT_ID") and not os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        print("WARNING: No Railway volume attached; SQLite data will be lost on redeploy", file=sys.stderr)

    from .storage import connect

    connect(db_path).close()  # initialize schema before both processes open it

    collector = [
        sys.executable, "-m", "mempool_scout.cli", "collect", "--db", db_path,
        "--vantage", os.environ.get("SCOUT_VANTAGE", "railway"),
        "--fetch-mode", fetch_mode,
    ]
    api = [
        sys.executable, "-m", "mempool_scout.cli", "serve", "--db", db_path,
        "--host", "0.0.0.0", "--port", port,
    ]
    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(subprocess.Popen(api))
        processes.append(subprocess.Popen(collector))
        while not stopping:
            for proc in processes:
                if proc.poll() is not None:
                    print(f"Process {proc.pid} exited ({proc.returncode}); stopping service", file=sys.stderr)
                    return proc.returncode or 1
            time.sleep(0.5)
        return 0
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    sys.exit(main())
