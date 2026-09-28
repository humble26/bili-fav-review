"""stats：复习库概况 + 未来 7 天到期分布 + 近期复习量。"""

from datetime import date, timedelta

from .. import ui
from ..config import load_config
from ..paths import db_path
from ..store import Store


def run(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        c = store.counts()
        ui.kv_table(
            "复习库概况",
            [
                ("收藏视频", c["total"]),
                ("有字幕全文", c["with_transcript"]),
                ("有摘要卡片", c["with_summary"]),
                ("复习进行中", c["learning"]),
                ("长记忆(间隔≥21天)", c["mature"]),
            ],
        )
        today = date.today().isoformat()
        hist = store.due_histogram(today, days=7)
        if hist:
            ui.rule("未来 7 天到期分布")
            peak = max(n for _, n in hist) or 1
            for d, n in hist:
                ui.info(f"  {d:<10} {ui.bar(round(n / peak * 100))} {n}")
        else:
            ui.info("未来 7 天没有到期卡片（先 sync 一批收藏吧）")

        week_ago = int((date.today() - timedelta(days=6)).strftime("%Y%m%d"))
        recent = store.conn.execute(
            "SELECT COUNT(*) FROM review_state WHERE last_review >= ?", (week_ago,)
        ).fetchone()[0]
        ui.kv_table("近 7 天", [("已复习卡片次数", recent)])
        return 0
    finally:
        store.close()
