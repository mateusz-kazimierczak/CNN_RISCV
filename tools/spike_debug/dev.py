"""Supervise the unified app dev server pair without touching existing servers."""

import argparse, os, signal, subprocess, sys, time
from tools.profile_spike import ROOT


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--configuration", default="B0")
    options, _ = parser.parse_known_args()
    children = []

    def stop(*_):
        for p in children:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(
            subprocess.Popen(
                [sys.executable, "-m", "tools.spike_debug.server", *sys.argv[1:]],
                cwd=ROOT,
                start_new_session=True,
            )
        )
        children.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", "5174", "--strictPort"],
                cwd=ROOT / "explorer",
                env={**os.environ, "PROFILE_CONFIGURATION": options.configuration},
                start_new_session=True,
            )
        )
        print(
            "Open Execution Atlas (Explorer + Simulator): http://127.0.0.1:5174/",
            flush=True,
        )
        while all(p.poll() is None for p in children):
            time.sleep(0.25)
    finally:
        stop()
        for p in children:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


if __name__ == "__main__":
    main()
