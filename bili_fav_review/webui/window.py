"""图形界面入口：本地服务 + pywebview 原生窗口。

拿不到 pywebview / WebView2 时自动回退到 Edge 应用模式窗口（同一套页面、
同一个引擎），保证老系统也能打开；再不行就用默认浏览器兜底。
任何启动异常都会追加到 ~/.bili_fav_review/gui_error.log，绝不无声崩溃。
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from .. import __version__, paths
from .api import Api
from .server import create_server

WINDOW_TITLE = f"收藏夹遗忘曲线 · B站版 v{__version__}"
WINDOW_W, WINDOW_H = 1120, 780
MIN_W, MIN_H = 960, 660
# 兜底窗口：页面停止轮询（窗口已关闭）这么久后本进程自动退出
IDLE_EXIT_SECONDS = 300

_ACTIVE_API: Api | None = None


def _append_error_file(text: str) -> None:
    try:
        log = paths.default_data_dir() / "gui_error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
    except Exception:
        pass


def _thread_excepthook(args) -> None:
    import traceback

    err = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    _append_error_file(err)
    if _ACTIVE_API is not None:
        try:
            _ACTIVE_API.hub.put(
                "log",
                {"level": "error", "text": f"后台线程异常: {args.exc_value}（详情见 gui_error.log）"},
            )
        except Exception:
            pass


def _edge_path() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)") or "") / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles") or "") / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((p for p in candidates if p.is_file()), None)


def _wait_for_close(api: Api, proc: subprocess.Popen | None) -> None:
    """等界面窗口关闭后返回，好让服务跟着退出。

    已有 Edge 在运行时，`--app=` 的启动进程会把窗口交给既有进程后立刻退出，
    所以不能只看进程存活；页面每 450ms 轮询一次 /api/events，用「心跳静默」判断更可靠。
    """
    while True:
        alive = proc is not None and proc.poll() is None
        if not alive and time.monotonic() - api.last_activity > IDLE_EXIT_SECONDS:
            return
        time.sleep(5)


def _run_edge_app(url: str, api: Api) -> int:
    """Edge 应用模式窗口：与 WebView2 同一引擎，Windows 10/11 默认自带。"""
    edge = _edge_path()
    if edge is None:
        webbrowser.open(url)
        _append_error_file(f"未找到 Edge，已在默认浏览器打开界面：{url}")
        _wait_for_close(api, None)
        return 0
    proc = subprocess.Popen(
        [str(edge), f"--app={url}", f"--window-size={WINDOW_W},{WINDOW_H}"]
    )
    _wait_for_close(api, proc)
    return 0


def _run_window(url: str, api: Api) -> int:
    try:
        import webview
    except Exception as e:
        _append_error_file(f"pywebview 不可用（{e}），回退 Edge 应用模式窗口")
        return _run_edge_app(url, api)
    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(MIN_W, MIN_H),
            background_color="#f6f7f9",
        )
        # private_mode=False：保留 localStorage（界面偏好、字体设置），也避免缓存错乱
        webview.start(private_mode=False)
        return 0
    except Exception:
        import traceback

        _append_error_file("pywebview 启动失败，回退 Edge 应用模式：\n" + traceback.format_exc())
        return _run_edge_app(url, api)


def run_gui() -> int:
    global _ACTIVE_API
    threading.excepthook = _thread_excepthook
    try:
        api = Api()
        _ACTIVE_API = api
        httpd, token, port = create_server(api)
    except Exception:
        import traceback

        err = traceback.format_exc()
        _append_error_file(err)
        print(err)
        return 1

    url = f"http://127.0.0.1:{port}/?t={token}&v={__version__}"
    threading.Thread(target=httpd.serve_forever, daemon=True, name="bfr-http").start()
    api.hub.put("log", {"level": "info", "text": f"界面服务已就绪 · 127.0.0.1:{port}"})
    try:
        return _run_window(url, api)
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
        api.close()


if __name__ == "__main__":
    sys.exit(run_gui())
