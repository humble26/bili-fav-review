"""本地界面服务：只绑 127.0.0.1 + 一次性 token，供 pywebview / Edge 窗口加载。

路由：
  GET  /                     → static/index.html
  GET  /<静态文件>            → static/ 下的 html/js/css/svg
  GET  /fonts/<文件名>        → 数据目录 fonts/ 下的用户字体（@font-face 用）
  GET  /api/events?since=N   → 事件增量（日志 / 登录状态 / 二维码 …）
  POST /api/rpc              → {"method": "...", "params": {...}}

静态资源不缓存（杜绝旧界面/白屏），/api/* 一律校验 token（URL 的 ?t= 或 X-BFR-Token 头）。
"""

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .api import Api

STATIC_DIR = Path(__file__).resolve().parent / "static"

TEXT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
FONT_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BiliFavReview"
    API: Api
    TOKEN: str

    def log_message(self, fmt, *args):  # 请求日志对用户没有价值，静音
        pass

    # ---------------------------------------------------------------- 工具

    def _token_ok(self, query: dict) -> bool:
        tok = (query.get("t") or [""])[0] or self.headers.get("X-BFR-Token", "")
        return bool(tok) and secrets.compare_digest(tok, self.TOKEN)

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(
            status,
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        suffix = path.suffix.lower()
        ctype = TEXT_TYPES.get(suffix) or FONT_TYPES.get(suffix) or "application/octet-stream"
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"error": "read failed"}, 500)
            return
        self._send(200, body, ctype)

    # ---------------------------------------------------------------- 路由

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler 约定
        self.API.touch()
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)

        if path == "/api/events":
            if not self._token_ok(query):
                self._json({"error": "forbidden"}, 403)
                return
            try:
                since = int((query.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            self._json(self.API.hub.since(since))
            return

        if path.startswith("/fonts/"):
            name = unquote(path[len("/fonts/") :])
            if not name or "/" in name or "\\" in name or name.startswith("."):
                self._json({"error": "bad font name"}, 400)
                return
            self._serve_file(self.API.fonts_dir() / name)
            return

        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not target.is_relative_to(STATIC_DIR):
            self._json({"error": "bad path"}, 400)
            return
        if target.is_dir():
            target = target / "index.html"
        self._serve_file(target)

    def do_POST(self):  # noqa: N802
        self.API.touch()
        u = urlparse(self.path)
        if u.path != "/api/rpc":
            self._json({"error": "not found"}, 404)
            return
        if not self._token_ok(parse_qs(u.query)):
            self._json({"error": "forbidden"}, 403)
            return
        method = "?"
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            method = str(payload.get("method") or "")
            data = self.API.call(method, payload.get("params") or {})
            self._json({"ok": True, "data": data})
        except Exception as e:
            self.API._log("error", f"接口 {method} 失败: {e}")
            self._json({"ok": False, "error": str(e)})


def create_server(api: Api, token: str | None = None) -> tuple[ThreadingHTTPServer, str, int]:
    """在 127.0.0.1 的随机端口上启动界面服务，返回 (httpd, token, port)。"""
    token = token or secrets.token_urlsafe(18)

    class _Bound(Handler):
        API = api
        TOKEN = token

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Bound)
    httpd.daemon_threads = True
    return httpd, token, int(httpd.server_address[1])


if __name__ == "__main__":  # 开发用：浏览器直接打开打印出的地址即可调试界面
    _api = Api()
    _httpd, _token, _port = create_server(_api)
    print(f"界面服务已启动: http://127.0.0.1:{_port}/?t={_token}", flush=True)
    try:
        _httpd.serve_forever()
    except KeyboardInterrupt:
        pass
