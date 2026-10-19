"""Start a local manual playground without running LINE workers or provider warmup."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    import uvicorn

    print(f"\nLocal playground: http://127.0.0.1:{args.port}\n"
          "Demo is the default. Providers run only when you submit in live mode.\n"
          "No LINE worker or inbox. Stop with Ctrl+C.\n", flush=True)
    uvicorn.run("app.playground:app", host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
