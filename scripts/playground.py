"""Start a local manual playground without running LINE workers or provider warmup."""
from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address; use 0.0.0.0 inside Docker (default: loopback only)")
    parser.add_argument("--pipeline", choices=("baseline", "support"), default="baseline",
                        help="baseline: LINE exclusive KB/web pipeline; support: candidate support mode")
    parser.add_argument('--kb-retriever', choices=('legacy',), default='legacy',
                        help='legacy: non-framework hybrid retriever on the existing KB')
    parser.add_argument('--web-retriever', choices=('legacy', 'read'), default='legacy',
                        help='read: experimental planned search followed by reading source pages')
    parser.add_argument('--table-executor', choices=('off',), default='off',
                        help='off: table rows included directly in context')
    parser.add_argument("--support-json-mode", action="store_true", help="experimental provider JSON mode; compatibility unverified")
    args = parser.parse_args()
    if args.support_json_mode and args.pipeline != 'support':
        parser.error('--support-json-mode requires --pipeline support')
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.pipeline != 'baseline' and (args.kb_retriever != 'legacy' or args.web_retriever != 'legacy' or args.table_executor != 'off'):
        parser.error('retriever and table-executor options apply to the baseline/LINE pipeline only')
    os.environ['RAG_KB_RETRIEVER'] = args.kb_retriever
    os.environ['RAG_WEB_RETRIEVER'] = args.web_retriever
    os.environ['RAG_TABLE_EXECUTOR'] = args.table_executor

    import uvicorn
    from app.playground import app

    app.state.pipeline = args.pipeline
    app.state.support_json_mode = args.support_json_mode
    app.state.retriever_experimental = args.kb_retriever != 'legacy' or args.web_retriever != 'legacy' or args.table_executor != 'off'

    print(f"\nLocal playground: http://127.0.0.1:{args.port}\n"
          f"Pipeline: {args.pipeline}" + (" (experimental)\n" if args.pipeline != "baseline" else "\n") +
          f"KB retriever: {args.kb_retriever}; web retriever: {args.web_retriever}; table executor: {args.table_executor}\n" +
          ("Provider JSON mode: experimental; support is unverified.\n" if args.support_json_mode else "") +
          "Demo is the default. Providers run only when you submit in live mode.\n"
          "No LINE worker or inbox. Stop with Ctrl+C.\n", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
