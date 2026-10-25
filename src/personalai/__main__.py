import argparse
from pathlib import Path
import socket
import sys

import uvicorn

from .app import create_app


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="PersonalAI 本机服务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
    except OSError:
        print(f"无法启动：本机端口 {args.port} 已被占用或不可用。请关闭已有实例或用 --port 指定其他端口。", file=sys.stderr)
        raise SystemExit(1)
    print(f"PersonalAI 本地应用：http://127.0.0.1:{args.port}（按 Ctrl+C 停止）", flush=True)
    config = uvicorn.Config(create_app(data_dir=args.data_dir, port=args.port), access_log=False, log_level="warning")
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
