"""把复习卡导出为 Anki 牌组（.apkg），可在 Anki 里继续安排复习。"""

import html
import json
import re
from datetime import date
from pathlib import Path

from .. import ui
from ..config import load_config
from ..paths import db_path, resolve_data_dir
from ..store import Store


def _as_list(value) -> list[str]:
    """摘要字段可能是字符串或畸形结构，规整成字符串列表再用。"""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if str(x).strip()]
    return []


def _note_fields(v) -> tuple[str, str]:
    card = {}
    try:
        card = json.loads(v["summary_json"]) or {}
    except Exception:
        card = {}
    if not isinstance(card, dict):
        card = {}
    esc = html.escape

    front_lines = [f"<b>{esc(v['title'])}</b>"]
    if card.get("one_liner"):
        front_lines.append(esc(card["one_liner"]))
    # 畸形项（字符串/缺 question）直接跳过，别让一张脏卡毁掉整个导出
    quiz = [
        q for q in (card.get("quiz") or []) if isinstance(q, dict) and q.get("question")
    ]
    if quiz:
        front_lines.append("<br><i>自测：" + esc(quiz[0]["question"]) + "</i>")
    front = "<br>".join(front_lines)

    back_lines = []
    for k in _as_list(card.get("key_points")):
        back_lines.append(f"• {esc(k)}")
    for q in quiz:
        back_lines.append(f"<br><b>Q: {esc(q['question'])}</b>")
        if q.get("answer"):
            back_lines.append(f"A: {esc(q['answer'])}")
    keywords = _as_list(card.get("keywords"))
    if keywords:
        back_lines.append("<br><i>" + esc(" / ".join(keywords)) + "</i>")
    back_lines.append(
        f"<br><small>UP: {esc(v['upper_name'])} · "
        f"<a href='https://www.bilibili.com/video/{v['bvid']}'>原视频</a></small>"
    )
    return front, "<br>".join(back_lines)


def run(args) -> int:
    try:
        import genanki
    except ImportError:
        ui.error("缺少依赖 genanki，请先安装: pip install genanki")
        return 1

    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        rows = store.anki_cards()
        if not rows:
            ui.warn("还没有可导出的摘要卡片（先 sync / 补齐摘要）")
            return 0

        model = genanki.Model(
            1607392319,
            "BiliFavReview Card",
            fields=[{"name": "Front"}, {"name": "Back"}],
            templates=[
                {
                    "name": "Card 1",
                    "qfmt": "{{Front}}",
                    "afmt": "{{Front}}<hr id=answer>{{Back}}",
                }
            ],
        )
        deck = genanki.Deck(2059400110, args.deck or "B站收藏夹复习")
        for v in rows:
            front, back = _note_fields(v)
            # Anki 标签不允许空格等字符，只保留中文/字母/数字/连字符/下划线
            tag = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (v["folder_title"] or "收藏")).strip("_") or "收藏"
            deck.add_note(
                genanki.Note(
                    model=model,
                    fields=[front, back],
                    guid=genanki.guid_for(v["bvid"]),  # 稳定 GUID：重复导入不产生重复卡
                    tags=[tag],
                )
            )

        out = Path(args.out) if args.out else (
            resolve_data_dir(cfg) / "exports" / f"anki-{date.today():%Y%m%d}.apkg"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        genanki.Package(deck).write_to_file(str(out))
        ui.success(f"已导出 {len(rows)} 张卡片到: {out}")
        ui.info("在 Anki 中 文件→导入 即可使用；重复导出/导入会按 BV 号去重更新")
        return 0
    finally:
        store.close()
