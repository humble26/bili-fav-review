"""review：过今天的到期卡片——先回忆，再看答案，按诚实度评分排下次时间。"""

import json
from datetime import date

from .. import ui
from ..config import load_config
from ..paths import db_path
from ..store import Store, apply_review, new_state, GRADE_FORGOT, GRADE_FUZZY, GRADE_OK

_GRADE_MAP = {"1": GRADE_FORGOT, "2": GRADE_FUZZY, "3": GRADE_OK}


def _load_card(v) -> dict:
    if not v["summary_json"]:
        return {}
    try:
        return json.loads(v["summary_json"]) or {}
    except Exception:
        return {}


def _recall_lines(v, card: dict) -> list[str]:
    lines = [f"一句话: {card.get('one_liner') or (v['intro'][:70] if v['intro'] else '(暂无摘要)')}"]
    quiz = card.get("quiz") or []
    if quiz and quiz[0].get("question"):
        lines.append(f"自测: {quiz[0]['question']}")
    return lines


def _reveal_lines(v, card: dict) -> list[str]:
    lines = []
    kps = card.get("key_points") or []
    if kps:
        lines.append("要点:")
        lines += [f"  • {k}" for k in kps]
    for q in card.get("quiz") or []:
        if q.get("question"):
            lines.append(f"自测: {q['question']}")
            if q.get("answer"):
                lines.append(f"  答案: {q['answer']}")
    if card.get("keywords"):
        lines.append("关键词: " + " / ".join(card["keywords"]))
    if not lines:
        lines = [v["intro"] or "(该视频暂无字幕与摘要，可凭标题回忆后评分)"]
    return lines


def run(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        today = date.today()
        max_n = int((cfg.get("review") or {}).get("max_per_session", 30))
        if getattr(args, "limit", None):
            max_n = args.limit
        due = store.due_items(today.isoformat(), max_n)
        if not due:
            nxt = store.next_due_date()
            msg = "今天没有到期卡片 🎉"
            if nxt:
                msg += f" 下次到期: {nxt}"
            elif store.counts()["total"] == 0:
                msg = "收藏夹还是空的，先运行 sync 或 demo 添加数据"
            ui.success(msg)
            return 0

        ui.info(f"今天有 {len(due)} 张卡片到期。先回忆再评分：1=忘了 2=模糊 3=记得\n")
        done = 0
        for i, v in enumerate(due, 1):
            card = _load_card(v)
            ui.panel(
                f"[{i}/{len(due)}] {v['title']}",
                _recall_lines(v, card),
                subtitle=f"UP: {v['upper_name']} · {v['folder_title']}",
            )
            input("  在脑中回忆一下，然后按回车看答案…")
            ui.panel("答案", _reveal_lines(v, card))
            while True:
                ans = input("  评分 [1]忘了 [2]模糊 [3]记得 / s=跳过 / q=退出: ").strip().lower()
                if ans == "q":
                    ui.info(f"本次已复习 {done} 张，剩下的下次继续")
                    return 0
                if ans == "s":
                    ui.info("  已跳过（未计入复习）")
                    break
                if ans in _GRADE_MAP:
                    row = store.get_review_state(v["bvid"])
                    base = dict(row) if row else new_state(today.isoformat())
                    state = apply_review(base, _GRADE_MAP[ans], today)
                    store.save_review_state(v["bvid"], state)
                    done += 1
                    ui.info(f"  下次复习: {state['due_date']}（间隔 {state['interval_days']} 天）")
                    break
                ui.warn("  请输入 1 / 2 / 3 / s / q")

        remaining = store.due_count(today.isoformat())
        ui.rule("本次复习完成")
        if remaining:
            ui.info(f"今天还有 {remaining} 张到期，再接再厉！")
        else:
            ui.success("今天的卡片全部清空 🎉")
        return 0
    finally:
        store.close()
