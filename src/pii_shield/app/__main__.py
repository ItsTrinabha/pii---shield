"""python -m pii_shield.app [--port 8765] : the local web UI (127.0.0.1 only)."""

from __future__ import annotations

import argparse
import webbrowser


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(prog="cloak")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    print(f"Cloak on {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless/WSL: the URL is printed above
            pass
    uvicorn.run("pii_shield.app.server:app", host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
