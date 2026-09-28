"""命令行入口与子命令分发。"""

import argparse
import sys

from . import __version__
from .commands import account, demo, review, search, stats, sync


def _setup_windows_stdio() -> None:
    """Windows 下输出编码跟随控制台代码页。

    - 交互控制台: Python 原生走 WriteConsoleW，永远正确，不做任何改动；
    - 管道/重定向: 跟随 GetConsoleOutputCP（zh-CN 默认 GBK，与 type/记事本一致），
      不可编码字符替换而非抛错；
    - 无控制台（计划任务等）: 退回 UTF-8。
    放在 main() 里是因为 pip 安装出的 bili-review.exe 入口不经过 __main__.py。
    """
    if sys.platform != "win32":
        return
    try:
        if sys.stdout.isatty() and sys.stderr.isatty():
            return
    except Exception:
        return
    try:
        import ctypes

        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
    except Exception:
        cp = 0
    enc = "utf-8" if cp in (0, 65001) else f"cp{cp}"
    try:
        sys.stdout.reconfigure(encoding=enc, errors="replace")
        sys.stderr.reconfigure(encoding=enc, errors="replace")
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m bili_fav_review",
        description="收藏夹遗忘曲线 · B站版 — 把B站收藏夹变成会主动找你复习的知识库",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="指定 config.toml 路径（默认 ./config.toml 或 ~/.bili_fav_review/config.toml）")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("login", help="扫码登录 B 站并保存登录态")
    sp.set_defaults(func=account.run_login)

    sp = sub.add_parser("folders", help="列出账号的收藏夹")
    sp.set_defaults(func=account.run_folders)

    sp = sub.add_parser("sync", help="同步收藏夹：元数据 + 字幕 + LLM 摘要（增量）")
    sp.add_argument("--folder", type=int, action="append", help="指定收藏夹 id，可重复")
    sp.add_argument("--all", action="store_true", help="同步全部收藏夹")
    sp.add_argument("--limit", type=int, help="本次处理上限（字幕/摘要各自生效）")
    sp.add_argument("--no-subtitles", action="store_true", help="跳过字幕抓取")
    sp.add_argument("--no-llm", action="store_true", help="跳过 LLM 摘要")
    sp.set_defaults(func=sync.run)

    sp = sub.add_parser("summarize", help="只补齐缺失的 AI 摘要（不重新拉字幕，增量）")
    sp.add_argument("--limit", type=int, default=40, help="本次最多生成多少张")
    sp.set_defaults(func=sync.run_summaries)

    sp = sub.add_parser("export-anki", help="导出复习卡为 Anki 牌组（.apkg）")
    sp.add_argument("--out", help="输出文件路径（默认数据目录 exports/ 下）")
    sp.add_argument("--deck", help="牌组名（默认: B站收藏夹复习）")
    sp.set_defaults(func=_run_anki)

    sp = sub.add_parser("review", help="复习今天的到期卡片")
    sp.add_argument("--limit", type=int, help="本次最多复习几张")
    sp.set_defaults(func=review.run)

    sp = sub.add_parser("due", help="查看今天到期数量（可发系统通知，配合任务计划程序）")
    sp.add_argument("--notify", action="store_true", help="有到期卡片时弹 Windows Toast 通知")
    sp.set_defaults(func=account.run_due)

    sp = sub.add_parser("search", help="全文搜索收藏（标题/简介/字幕/摘要）")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(func=search.run_search)

    sp = sub.add_parser("show", help="查看某个视频的完整卡片")
    sp.add_argument("bvid")
    sp.set_defaults(func=search.run_show)

    sp = sub.add_parser("stats", help="复习库统计")
    sp.set_defaults(func=stats.run)

    sp = sub.add_parser("gui", help="打开图形界面（适合日常使用，无需记命令）")
    sp.set_defaults(func=lambda args: _run_gui())

    sp = sub.add_parser("demo", help="内置演示数据（无需登录即可体验全流程）")
    sp.add_argument("--clear", action="store_true", help="清除演示数据")
    sp.set_defaults(func=demo.run)

    return p


def _run_gui() -> int:
    from .webui.window import run_gui  # 延迟导入，界面栈缺失也不影响其他命令

    return run_gui()


def _run_anki(args) -> int:
    from .commands import anki_export  # 延迟导入，genanki 为可选依赖

    return anki_export.run(args)


def main(argv=None) -> int:
    _setup_windows_stdio()
    args = build_parser().parse_args(argv)
    return args.func(args) or 0
