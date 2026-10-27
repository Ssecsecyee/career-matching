"""Local-only process supervisor. Watches Python sources and .env; never calls AWS."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def signature(root):
    paths = {root / ".env", root / "local_server.py"}
    source = root / "src"
    if source.exists():
        paths.update(source.rglob("*.py"))
    result = {}
    for path in paths:
        try:
            info = path.stat()
            result[str(path.relative_to(root))] = (info.st_mtime_ns, info.st_size)
        except FileNotFoundError:
            continue
    return result


def start(root, port):
    environment = dict(os.environ, PYTHONUNBUFFERED="1", LOCAL_API_PORT=str(port))
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    return subprocess.Popen([sys.executable, str(root / "local_server.py")], cwd=root,
                            env=environment, **options)


def stop(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=8)
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "local_server.py").is_file() or not 1 <= args.port <= 65535:
        parser.error("Valid backend root and port required")
    if hasattr(signal, "SIGBREAK"):
        def interrupt(signum, frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGBREAK, interrupt)
    previous = signature(root)
    child = None
    exit_reported = False
    print(f"Auto-reload API: http://127.0.0.1:{args.port}", flush=True)
    print("Watching src/**/*.py, local_server.py and .env. Ctrl+C to stop.", flush=True)
    try:
        child = start(root, args.port)
        while True:
            time.sleep(.3)
            current = signature(root)
            if current != previous:
                # Wait for editors that save in several filesystem operations.
                time.sleep(.4)
                current = signature(root)
                print("Backend files changed; restarting API.", flush=True)
                stop(child)
                child = start(root, args.port)
                previous = current
                exit_reported = False
            elif child.poll() is not None and not exit_reported:
                print("API stopped. Check the error above; fix/save to retry. If the port is busy, stop the older server.", flush=True)
                exit_reported = True
    except KeyboardInterrupt:
        print("\nStopping local API watcher.", flush=True)
    finally:
        stop(child)


if __name__ == "__main__":
    main()

