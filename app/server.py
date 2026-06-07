"""
壹米云相册 - 服务器入口
支持 gunicorn（生产）和内置 WSGI（开发）
"""
import os
import sys
import socket
import socketserver
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler


class ThreadedWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        if str(code) not in ("304", "200"):
            super().log_request(code, size)


def run_dev_server(app, host="0.0.0.0", port=8080):
    """开发模式: 内置多线程 WSGI"""
    server = ThreadedWSGIServer((host, port), QuietHandler)
    server.set_app(app)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    print(f" * Yimi-Photo v3.0.0 running on http://{host}:{port}")
    print(f" * Threaded WSGI mode")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n * Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    run_dev_server(app, port=port)

