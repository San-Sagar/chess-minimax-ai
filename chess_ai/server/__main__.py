"""Start the server: ``python -m chess_ai.server [--port 8000] [--host 127.0.0.1]``.

On a hosting service, set the environment variables instead:
``HOST`` (use 0.0.0.0 to accept outside connections) and ``PORT``.
"""

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Chess Minimax AI web server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()
    uvicorn.run("chess_ai.server.app:app", host=args.host, port=args.port, reload=args.reload,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
