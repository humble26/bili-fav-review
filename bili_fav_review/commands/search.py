"""search / show：全文检索收藏（标题+简介+字幕+摘要），查看完整卡片。"""

import json

from .. import ui
from ..config import load_config
from ..paths import db_path
from ..store import Store, make_snippet


def run_search(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        rows = store.search(args.query, args.limit)
        if not rows:
            ui.warn(f"没有找到包含“{args.query}”的收藏")
            return 0
        for i, r in enumerate(rows, 1):
            snip = (r["snip"] if "snip" in r.keys() else None) or make_snippet(r, args.query)
            ui.info(f"[{i}] {r['title']}  ({r['bvid']})")
            ui.info(f"    {snip.strip()[:160]}")
        ui.info("\n查看完整卡片: python -m bili_fav_review show <bvid>")
        return 0
    finally:
        store.close()


def run_show(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        v = store.get_video(args.bvid)
        if v is None:
            ui.error(f"没有找到 {args.bvid}")
            return 1
        card = {}
        if v["summary_json"]:
            try:
                card = json.loads(v["summary_json"]) or {}
            except Exception:
                card = {}
        if not isinstance(card, dict):
            card = {}
        st = store.get_review_state(args.bvid)
        lines = [
            f"UP: {v['upper_name']}    收藏夹: {v['folder_title']}",
        ]
        if card.get("one_liner"):
            lines.append(f"一句话: {card['one_liner']}")
        kps = card.get("key_points")
        kps = [kps] if isinstance(kps, str) else (kps or [])
        if kps:
            lines.append("要点:")
            lines += [f"  • {k}" for k in kps]
        kws = card.get("keywords")
        kws = [kws] if isinstance(kws, str) else (kws or [])
        if kws:
            lines.append("关键词: " + " / ".join(str(k) for k in kws))
        for q in card.get("quiz") or []:
            if not isinstance(q, dict) or not q.get("question"):
                continue
            lines.append(f"自测: {q.get('question', '')}")
            if q.get("answer"):
                lines.append(f"  答案: {q['answer']}")
        if v["transcript"]:
            lines.append(f"字幕({v['subtitle_lang']})节选: {v['transcript'][:300].replace(chr(10), ' ')}…")
        elif v["subtitle_note"]:
            lines.append(f"字幕: {v['subtitle_note']}")
        if st:
            lines.append(
                f"复习状态: 到期 {st['due_date']} · 已记 {st['reps']} 次 · 忘过 {st['lapses']} 次 · 间隔 {st['interval_days']} 天"
            )
        ui.panel(v["title"], lines, subtitle=v["bvid"])
        return 0
    finally:
        store.close()
