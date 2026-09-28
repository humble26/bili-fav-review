"""sync：同步收藏夹 → 拉字幕 → LLM 摘要，三段式增量同步。"""

from datetime import date, timedelta

from .. import ui
from ..bilibili import BilibiliClient, NotLoggedInError, load_cookies
from ..config import load_config, validate_llm
from ..paths import cookies_path, db_path, resolve_data_dir
from ..store import Store
from ..summarize import summarize, summarize_intro_batch


def _resolve_folders(client: BilibiliClient, mid: int, args, cfg: dict, store: Store) -> list[dict]:
    folders = client.list_folders(mid)
    by_id = {f["id"]: f for f in folders}
    if getattr(args, "all", False):
        return folders

    ids = list(getattr(args, "folder", None) or [])
    if not ids:
        ids = store.setting_get("folders") or (cfg.get("bilibili") or {}).get("folders") or []
    if not ids:
        ui.data_table(
            ["序号", "ID", "标题", "视频数"],
            [[i + 1, f["id"], f["title"], f["media_count"]] for i, f in enumerate(folders)],
            title="你的收藏夹",
        )
        raw = input("选择要同步的序号（逗号分隔，a=全部，回车=全部）: ").strip().lower()
        if raw in ("", "a", "all"):
            ids = [f["id"] for f in folders]
        else:
            picked = []
            for tok in raw.replace("，", ",").split(","):
                tok = tok.strip()
                if tok.isdigit() and 0 <= int(tok) - 1 < len(folders):
                    picked.append(folders[int(tok) - 1]["id"])
            ids = picked
        store.setting_set("folders", ids)
        ui.info(f"已记住选择（临时换夹子可用 sync --folder <id>）: {ids}")

    out = []
    for i in ids:
        if int(i) in by_id:
            out.append(by_id[int(i)])
        else:
            ui.warn(f"收藏夹 {i} 不存在，已跳过")
    return out


def _sync_metadata(client: BilibiliClient, folders: list[dict], store: Store, cfg: dict) -> int:
    new_due_days = (cfg.get("review") or {}).get("new_due_days", 1)
    first_due = (date.today() + timedelta(days=new_due_days)).isoformat()
    new_cnt = 0
    for f in folders:
        cnt = 0
        for m in client.iter_folder_videos(f["id"]):
            # type=2 为普通视频；失效视频没有 bvid，直接跳过
            if m.get("type") != 2 or not m.get("bvid") or m.get("title") == "已失效视频":
                continue
            v = {
                "bvid": m["bvid"],
                "aid": m.get("id"),
                "cid": None,
                "title": m.get("title", ""),
                "intro": (m.get("intro") or "")[:2000],
                "upper_name": (m.get("upper") or {}).get("name", ""),
                "duration": m.get("duration", 0),
                "folder_id": f["id"],
                "folder_title": f.get("title", ""),
                "fav_time": m.get("fav_time"),
                "pubtime": m.get("pubtime"),
            }
            if store.upsert_video(v):
                store.init_review(v["bvid"], first_due)
                new_cnt += 1
            cnt += 1
        ui.info(f"  《{f.get('title')}》{cnt} 个视频")
    return new_cnt


def _fetch_transcripts(client: BilibiliClient, store: Store, cfg: dict, limit: int):
    priority = (cfg.get("bilibili") or {}).get("subtitle_priority") or ["zh-Hans", "ai-zh"]
    targets = store.videos_needing_transcript(limit)
    ok = miss = fail = 0
    for i, v in enumerate(targets, 1):
        ui.info(f"[{i}/{len(targets)}] 拉字幕: {v['title'][:44]} ({v['bvid']})")
        try:
            view = client.get_view(v["bvid"])
            cid = view.get("cid")
            subs = client.get_subtitle_list(v["bvid"], cid) if cid else []
            pick = client.pick_subtitle(subs, priority)
            if not pick or not pick.get("subtitle_url"):
                store.mark_subtitle_checked(v["bvid"], "无CC/AI字幕（仅标题+简介参与摘要）")
                miss += 1
                ui.warn("    无可用字幕")
            else:
                lang, text = client.fetch_subtitle_text(pick["subtitle_url"])
                store.save_transcript(v["bvid"], cid, lang, text)
                ok += 1
                ui.success(f"    字幕 {lang}，{len(text)} 字")
        except NotLoggedInError:
            raise  # 登录失效时中止整个字幕阶段，交由上层给出明确提示
        except Exception as e:
            # 单个视频失败（含网络抖动）绝不炸掉整个阶段；不标记 checked，下次 sync 自动重试
            fail += 1
            ui.error(f"    拉取失败: {e}（下次 sync 自动重试）")
    return ok, miss, fail


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _title_only_card(v) -> dict:
    return {
        "one_liner": v["title"],
        "key_points": [],
        "keywords": [],
        "quiz": [],
        "source": "title_only",
    }


def fill_summaries(store: Store, cfg: dict, limit: int) -> int:
    """补齐缺失摘要，三档成本策略（返回本次生成张数）：

    ① 有字幕全文 → 单条精摘（质量优先，成本最高但价值也最高）
    ② 无字幕、有标题/简介 → 批量轻摘（8 条合并一次调用，只出"看点预告"）
    ③ 标题简介都缺失 → 本地占位卡（零 AI 消耗）
    已有摘要的永不重复生成；失败的记入 summary_error，24h 后自动重试。
    """
    llm = cfg.get("llm") or {}
    if not llm.get("enabled", True):
        return 0
    problems = validate_llm(cfg)
    if problems:
        for p in problems:
            ui.warn(p)
        return 0
    batch_size = max(1, int(llm.get("batch_intro_size", 8)))
    made = 0

    # ① 精摘
    targets = store.videos_needing_summary(limit, mode="full")
    for i, v in enumerate(targets, 1):
        ui.info(f"[{i}/{len(targets)}] 精摘: {v['title'][:44]} ({v['bvid']})")
        try:
            card = summarize(v["title"], v["intro"], v["transcript"], llm)
            card["source"] = "subtitle"
            store.save_summary(v["bvid"], card)
            made += 1
            ui.success(f"    {card['one_liner'] or '(空概括)'}")
        except Exception as e:
            store.mark_summary_error(v["bvid"], str(e))
            ui.error(f"    {e}")

    # ② 批量轻摘（标题+简介，含尚未检查过字幕的视频——之后 sync 拉到字幕会自动覆盖升级）
    thin = store.videos_needing_summary(limit, mode="intro")
    worth_llm, fallback = [], []
    for v in thin:
        if len((v["intro"] or "").strip()) + len(v["title"]) >= 20:
            worth_llm.append(v)
        else:
            fallback.append(v)
    for chunk in _chunks(worth_llm, batch_size):
        items = [
            {"i": idx, "title": v["title"], "intro": v["intro"]}
            for idx, v in enumerate(chunk)
        ]
        ui.info(f"批量轻摘 {len(chunk)} 个无字幕视频（合并为一次 AI 调用）…")
        try:
            cards = summarize_intro_batch(items, llm)
        except Exception as e:
            ui.error(f"    {e}")
            # 400 类错误多为平台内容审核拒绝，重试无意义 → 直接零 AI 兜底；
            # 其他错误（网络等）记入 error，24h 后自动重试
            if "400" in str(e) or "Bad Request" in str(e):
                for v in chunk:
                    store.save_summary(v["bvid"], _title_only_card(v))
                    made += 1
                    ui.info(f"    [兜底] {v['title'][:44]}（AI 拒绝该内容，本地生成）")
            else:
                for v in chunk:
                    store.mark_summary_error(v["bvid"], f"批量摘要失败: {e}")
            continue
        for idx, v in enumerate(chunk):
            card = cards.get(idx)
            if card:
                card["source"] = "intro"
                store.save_summary(v["bvid"], card)
                made += 1
                ui.success(f"    [{idx}] {card['one_liner'] or '(空)'}")
            else:
                store.save_summary(v["bvid"], _title_only_card(v))
                made += 1

    # ③ 零 AI 兜底
    for v in fallback:
        store.save_summary(v["bvid"], _title_only_card(v))
        made += 1
        ui.info(f"    [兜底] {v['title'][:44]}（无简介，跳过 AI）")
    return made


def run_summaries(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        n = fill_summaries(store, cfg, args.limit)
        ui.info(f"摘要: 新增 {n} 张卡片")
        if n >= args.limit:
            ui.info(f"可能还有缺漏，再跑一次: python -m bili_fav_review summarize --limit {args.limit}")
        return 0
    finally:
        store.close()


def run(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        try:
            if store.backup():
                ui.success("已自动备份数据库（保留最近 7 份）")
        except Exception as e:
            ui.warn(f"自动备份失败（不影响同步）: {e}")
        cookies = load_cookies(cookies_path(cfg))
        if not cookies:
            ui.error("尚未登录。请先运行: python -m bili_fav_review login")
            return 1
        sync_cfg = cfg.get("sync") or {}
        client = BilibiliClient(
            cookies,
            interval=sync_cfg.get("request_interval", 1.0),
            wbi_cache=resolve_data_dir(cfg) / "wbi_cache.json",
        )
        try:
            me = client.me()
        except NotLoggedInError as e:
            ui.error(str(e))
            return 1
        ui.info(f"已登录: {me.get('uname')} (UID {me.get('mid')})")

        folders = _resolve_folders(client, me["mid"], args, cfg, store)
        if not folders:
            ui.warn("没有可同步的收藏夹")
            return 0
        cap = args.limit or 0

        ui.rule("① 同步收藏夹元数据")
        new_cnt = _sync_metadata(client, folders, store, cfg)
        ui.success(f"新增 {new_cnt} 个视频")

        if not args.no_subtitles:
            ui.rule("② 拉取字幕")
            ok, miss, fail = _fetch_transcripts(
                client, store, cfg, cap or int(sync_cfg.get("videos_per_run", 40))
            )
            ui.info(f"字幕: 成功 {ok} / 无字幕 {miss} / 失败 {fail}")

        if not args.no_llm:
            ui.rule("③ LLM 摘要")
            n = fill_summaries(
                store, cfg, cap or int(sync_cfg.get("summaries_per_run", 40))
            )
            ui.info(f"摘要: 新增 {n} 张卡片")

        ui.rule("完成")
        ui.info("复习到期卡片: python -m bili_fav_review review")
        return 0
    finally:
        store.close()
