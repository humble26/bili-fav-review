"""界面后端接口：把 store/*、commands/* 的能力暴露成本地 JSON-RPC。

与 CLI 共用同一套业务逻辑，界面层不重复实现任何业务。
每个请求线程各自持有 SQLite 连接（threading.local），写操作串行化（RLock）。
所有网络/耗时操作放进后台线程，结果通过 EventHub 推给前端。
"""

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

from .. import __version__, ui
from .. import config as config_mod
from ..bilibili import BilibiliClient, load_cookies, qr_login, save_cookies
from ..commands.review import _load_card
from ..paths import cookies_path, db_path, resolve_data_dir
from ..store import (
    GRADE_FORGOT,
    GRADE_FUZZY,
    GRADE_OK,
    Store,
    apply_review,
    make_snippet,
    new_state,
)
from .content import GUIDE_STEPS, HELP_TEXT
from .hub import EventHub

TASK_NAME = "BiliFavReview"
GRADE_LABEL = {GRADE_FORGOT: "忘了", GRADE_FUZZY: "模糊", GRADE_OK: "记得"}
_EXTERNAL_HOSTS = ("bilibili.com", "b23.tv")
CARD_LIST_CAP = 1000  # 卡片库一次性最多返回多少行，避免超大收藏库把页面拖卡
CARD_FILTERS = ("新卡", "今日到期", "已逾期", "长期记忆", "复习中")


def _as_str_list(value) -> list[str]:
    """把 LLM 生成的摘要字段规整成字符串列表（畸形数据不能把整页搞崩）。"""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [s for s in (str(v).strip() for v in value) if s]
    return []


def _as_int_list(value) -> list[int]:
    out: list[int] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        text = str(item).strip()
        if text.lstrip("-").isdigit():
            out.append(int(text))
    return out


def _card_status(reps, due_date, interval_days, today: str) -> str:
    """卡片库筛选用的纯文本状态（与前端筛选器选项一致）。"""
    if not reps:
        return "新卡"
    if due_date and due_date < today:
        return "已逾期"
    if due_date == today:
        return "今日到期"
    if (interval_days or 0) >= 21:
        return "长期记忆"
    return "复习中"


def _card_row(r, status: str) -> dict:
    """卡片库列表用的精简行（不带字幕全文，避免大库时响应过大）。"""
    return {
        "bvid": r["bvid"],
        "title": str(r["title"] or ""),
        "upper": str(r["upper_name"] or ""),
        "folder": str(r["folder_title"] or ""),
        "status": status,
        "due": r["due_date"],
        "interval": r["interval_days"],
        "reps": r["reps"] or 0,
        "lapses": r["lapses"] or 0,
        "has_summary": bool(r["summary_json"]),
        "has_transcript": bool(r["transcript"]),
    }


def _norm_hhmm(value: str) -> str:
    """把用户输入的时间规整成 schtasks 要求的 HH:MM（中文全角冒号、9:5 都算合法输入）。"""
    text = (value or "").strip() or "09:30"
    try:
        hh, mm = (int(x) for x in text.replace("：", ":").split(":"))
    except Exception:
        raise RuntimeError(f"时间格式应为 HH:MM，例如 09:30（收到：{value!r}）")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise RuntimeError(f"时间超出范围：{value!r}（小时 0-23，分钟 0-59）")
    return f"{hh:02d}:{mm:02d}"


def _card_payload(row) -> dict:
    """把一条到期记录整理成前端渲染所需的结构（答案侧与「回忆」侧分开）。"""
    card = _load_card(row)
    source = card.get("source")
    if source == "intro":
        note = "本卡由标题+简介生成（视频无字幕），要点为看点预告"
    elif source == "title_only":
        note = "本视频暂无字幕和简介，建议点「重看视频」直接观看"
    else:
        note = None
    quiz = [
        {
            "question": str(q.get("question", "")).strip(),
            "answer": str(q.get("answer", "")).strip(),
        }
        for q in (card.get("quiz") or [])
        if isinstance(q, dict) and str(q.get("question", "")).strip()
    ]
    key_points = _as_str_list(card.get("key_points"))
    keywords = _as_str_list(card.get("keywords"))
    fallback = None
    if not (key_points or quiz or keywords):
        fallback = row["intro"] or "（该视频暂无字幕与摘要，可凭标题回忆后评分）"
    return {
        "bvid": row["bvid"],
        "title": str(row["title"] or ""),
        "upper": str(row["upper_name"] or ""),
        "folder": str(row["folder_title"] or ""),
        "url": f"https://www.bilibili.com/video/{row['bvid']}",
        "is_new": (row["reps"] or 0) == 0,
        "reps": row["reps"] or 0,
        "lapses": row["lapses"] or 0,
        "one_liner": str(card.get("one_liner") or (row["intro"] or "")[:90]),
        "quiz_question": quiz[0]["question"] if quiz else "",
        "answer": {
            "note": note,
            "key_points": key_points,
            "quiz": quiz,
            "keywords": keywords,
            "fallback": fallback,
        },
    }


class Api:
    def __init__(self):
        self.hub = EventHub()
        self._last_cfg_err: str | None = None
        self.cfg, _ = config_mod.load_config()
        self.cfg_path = config_mod.resolve_config_path()
        # 配置解析未抛异常不代表没问题：语法错误时会回退默认配置并备份原文件，
        # 必须把原因推给界面，否则用户会以为自己的设置莫名其妙丢了。
        self._report_cfg_error()
        self._local = threading.local()
        self._lock = threading.RLock()
        self._undo: tuple[str, dict | None] | None = None
        self._login_busy = False
        self._login_cancel = False
        self._backed_up = False
        self._folders_busy = False
        self._sync_busy = False
        self._fill_busy = False
        self._anki_busy = False
        self.last_activity = time.monotonic()
        ui.set_sink(self._log)

    def touch(self) -> None:
        """每次界面请求刷新一次心跳：兜底窗口靠它判断页面是否还开着。"""
        self.last_activity = time.monotonic()

    # ---------------------------------------------------------------- 基础设施

    def _log(self, level: str, text: str) -> None:
        """界面日志唯一出口：写 gui.log 文件 + 推给前端日志面板。"""
        try:
            log = resolve_data_dir(self.cfg) / "gui.log"
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {text}\n")
        except Exception:
            pass
        self.hub.put("log", {"level": level, "text": text})

    def store(self) -> Store:
        st = getattr(self._local, "store", None)
        if st is None:
            st = Store(db_path(self.cfg))
            try:  # 多连接（HTTP 线程 + 后台线程）下 WAL 明显更稳
                st.conn.execute("PRAGMA journal_mode=WAL")
                st.conn.commit()
            except Exception:
                pass
            self._local.store = st
        return st

    def close(self) -> None:
        st = getattr(self._local, "store", None)
        if st is not None:
            try:
                st.close()
            except Exception:
                pass
            self._local.store = None

    def _client(self) -> BilibiliClient:
        interval = (self.cfg.get("sync") or {}).get("request_interval", 1.0)
        return BilibiliClient(
            load_cookies(cookies_path(self.cfg)) or {},
            interval=max(0.6, float(interval)),
            wbi_cache=resolve_data_dir(self.cfg) / "wbi_cache.json",
        )

    def refresh_config(self) -> None:
        self.cfg, _ = config_mod.load_config()
        self.cfg_path = config_mod.resolve_config_path()
        self._report_cfg_error()

    def _report_cfg_error(self) -> None:
        """把配置问题推给界面；同一条只报一次（本方法在每次界面刷新时都会走到）。"""
        err = config_mod.last_load_error()
        if err and err != self._last_cfg_err:
            self.hub.put("log", {"level": "error", "text": err})
        self._last_cfg_err = err

    def call(self, method: str, params: dict | None = None) -> dict:
        fn = getattr(self, f"rpc_{method}", None)
        if fn is None:
            raise RuntimeError(f"未知接口: {method}")
        return fn(**(params or {}))

    # ---------------------------------------------------------------- 启动与主页

    def rpc_bootstrap(self) -> dict:
        self.refresh_config()
        self._backup_once()
        return {
            "version": __version__,
            "data_dir": str(resolve_data_dir(self.cfg)),
            "home": self._home_data(),
            "settings": self._settings_data(),
            "task": self._task_data(),
            "guide_steps": GUIDE_STEPS,
        }

    def _backup_once(self) -> None:
        """每日自动备份数据库（与旧界面 refresh_all 的行为一致，保留最近 7 份）。"""
        if self._backed_up:
            return
        self._backed_up = True
        try:
            if self.store().backup():
                self._log("success", "已自动备份数据库（保留最近 7 份）")
        except Exception as e:
            self._log("warn", f"自动备份失败（不影响使用）: {e}")

    def rpc_home(self) -> dict:
        return self._home_data()

    def _home_data(self) -> dict:
        today = date.today().isoformat()
        st = self.store()
        due_new, due_old = st.due_breakdown(today)
        return {
            "counts": st.counts(),
            "due": {"new": due_new, "old": due_old, "total": due_new + due_old},
            "next_due": st.next_due_date(),
            "promotable": st.promotable_count(today),
        }

    def rpc_content(self) -> dict:
        return {"help": HELP_TEXT}

    def rpc_note(self, level: str = "info", text: str = "") -> dict:
        """界面侧产生的日志（跳过卡片等），与后端日志走同一条出口。"""
        self._log(level if level in ("info", "success", "warn", "error", "rule") else "info", text)
        return {"ok": True}

    def rpc_settings(self) -> dict:
        self.refresh_config()
        return {"settings": self._settings_data(), "task": self._task_data()}

    def rpc_fonts(self) -> dict:
        folder = self.fonts_dir()
        files = []
        if folder.exists():
            for f in sorted(folder.iterdir()):
                if f.is_file() and f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                    files.append({"name": f.name, "url": "/fonts/" + quote(f.name)})
        return {"files": files}

    def fonts_dir(self) -> Path:
        return resolve_data_dir(self.cfg) / "fonts"

    # ---------------------------------------------------------------- 登录

    def rpc_check_login(self) -> dict:
        threading.Thread(target=self._check_login_worker, daemon=True).start()
        return {"started": True}

    def _check_login_worker(self) -> None:
        cookies = load_cookies(cookies_path(self.cfg))
        if not cookies:
            self.hub.put("login_state", {"ok": False, "text": "未登录 —— 点右上角「扫码登录」"})
            return
        try:
            me = self._client().me()
            self.hub.put("login_state", {"ok": True, "text": f"已登录 · {me.get('uname')}"})
        except Exception as e:
            self.hub.put("login_state", {"ok": False, "text": f"登录已失效，请重新扫码（{e}）"})

    def rpc_login_start(self) -> dict:
        if self._login_busy:
            return {"started": False}
        self._login_busy = True
        self._login_cancel = False
        threading.Thread(target=self._login_worker, daemon=True).start()
        return {"started": True}

    def rpc_login_cancel(self) -> dict:
        self._login_cancel = True
        return {"ok": True}

    def _login_worker(self) -> None:
        try:
            cookies = qr_login(
                render_qr=self._push_qr,
                on_status=lambda s: self.hub.put("login_status", {"text": s}),
                should_cancel=lambda: self._login_cancel,
            )
            save_cookies(cookies_path(self.cfg), cookies)
            self.hub.put("login_success", {"uid": cookies.get("DedeUserID", "?")})
        except Exception as e:
            self.hub.put("login_failed", {"error": str(e)})
        finally:
            self._login_busy = False

    def _push_qr(self, url: str) -> None:
        try:
            import qrcode

            qr = qrcode.QRCode(border=2)
            qr.add_data(url)
            qr.make(fit=True)
            matrix = ["".join("1" if c else "0" for c in row) for row in qr.get_matrix()]
        except Exception as e:
            self._log("error", f"二维码生成失败: {e}")
            return
        self.hub.put("qr", {"matrix": matrix, "size": len(matrix), "url": url})

    # ---------------------------------------------------------------- 复习

    def rpc_review_start(self) -> dict:
        today = date.today().isoformat()
        st = self.store()
        limit = int((self.cfg.get("review") or {}).get("max_per_session", 30))
        rows = st.due_items(today, limit)
        self._undo = None
        out = {"cards": [_card_payload(r) for r in rows], "session_limit": limit}
        if not out["cards"]:
            out.update(
                {
                    "next_due": st.next_due_date(),
                    "promotable": st.promotable_count(today),
                    "total_videos": st.counts()["total"],
                }
            )
        return out

    def rpc_review_grade(self, bvid: str, grade: int, title: str = "") -> dict:
        if not bvid or not isinstance(bvid, str):
            raise RuntimeError("缺少卡片 BV 号")
        try:
            grade = int(grade)
        except (TypeError, ValueError):
            raise RuntimeError(f"评分值不合法：{grade!r}")
        if grade not in GRADE_LABEL:
            raise RuntimeError(f"评分值不合法：{grade}")
        today = date.today()
        with self._lock:
            st = self.store()
            row = st.get_review_state(bvid)
            self._undo = (bvid, dict(row) if row else None)
            base = dict(row) if row else new_state(today.isoformat())
            state = apply_review(base, int(grade), today)
            st.save_review_state(bvid, state)
        label = GRADE_LABEL.get(int(grade), "?")
        self._log(
            "info",
            f"[{label}] {title[:36]} → 下次 {state['due_date']}（隔 {state['interval_days']} 天）",
        )
        return {
            "due_date": state["due_date"],
            "interval_days": state["interval_days"],
            "label": label,
            "remaining": self.store().due_count(today.isoformat()),
        }

    def rpc_review_undo(self) -> dict:
        if not self._undo:
            return {"ok": False}
        bvid, prev = self._undo
        with self._lock:
            st = self.store()
            st.save_review_state(
                bvid, prev or new_state(date.today().isoformat())
            )
        self._undo = None
        self._log("info", "已撤销上一次评分")
        return {"ok": True, "bvid": bvid}

    def rpc_review_promote(self) -> dict:
        n = self.store().promote_new_cards(date.today().isoformat())
        self._log("info", f"已把 {n} 张新卡片提前到今天")
        return {"moved": n}

    def rpc_review_summary(self) -> dict:
        today = date.today().isoformat()
        return {"remaining": self.store().due_count(today), "next_due": self.store().next_due_date()}

    # ---------------------------------------------------------------- 收藏夹与同步

    def rpc_folders(self) -> dict:
        """拉取收藏夹列表：网络操作放后台线程，结果走 folders / folders_error 事件。"""
        if self._folders_busy:
            return {"started": False}
        self._folders_busy = True
        self._log("info", "正在拉取收藏夹列表…")
        threading.Thread(target=self._folders_worker, daemon=True).start()
        return {"started": True}

    def _folders_worker(self) -> None:
        try:
            folders = self._fetch_folders()
            self.hub.put("folders", folders)
            self._log(
                "success",
                f"已拉取 {len(folders['items'])} 个收藏夹：勾选要同步的夹子，再点「开始同步」",
            )
        except Exception as e:
            self.hub.put("folders_error", {"error": str(e)})
            self._log("error", f"拉取收藏夹失败: {e}")
        finally:
            self._folders_busy = False

    def _fetch_folders(self) -> dict:
        cookies = load_cookies(cookies_path(self.cfg))
        if not cookies or not cookies.get("SESSDATA"):
            raise RuntimeError("尚未登录或登录态丢失，请点右上角「扫码登录」")
        client = self._client()
        me = client.me()  # 顺带校验登录态，报错信息最准确
        saved = set(_as_int_list(self.store().setting_get("folders") or []))
        items = []
        for f in client.list_folders(int(me["mid"])):
            fid = int(f["id"])
            items.append(
                {
                    "id": fid,
                    "title": str(f.get("title") or ""),
                    "count": int(f.get("media_count") or 0),
                    "selected": fid in saved,
                }
            )
        return {"items": items, "user": str(me.get("uname") or "")}

    def rpc_sync_start(self, folders=None, limit=None, with_llm: bool = True) -> dict:
        if self._sync_busy:
            return {"started": False, "error": "同步已经在进行中"}
        ids = _as_int_list(folders)
        if not ids:
            raise RuntimeError("请先在列表里勾选要同步的收藏夹")
        cookies = load_cookies(cookies_path(self.cfg))
        if not cookies or not cookies.get("SESSDATA"):
            raise RuntimeError("尚未登录，请先点右上角「扫码登录」")
        text = str(limit or "").strip()
        self.store().setting_set("folders", ids)
        self._sync_busy = True
        self.hub.put("sync_state", {"running": True})
        self._log("rule", "开始同步")
        threading.Thread(
            target=self._sync_worker,
            args=(ids, int(text) if text.isdigit() else None, bool(with_llm)),
            daemon=True,
        ).start()
        return {"started": True, "count": len(ids)}

    def _sync_worker(self, ids: list[int], limit: int | None, with_llm: bool) -> None:
        from ..commands import sync as sync_mod

        ok = False
        try:
            ns = SimpleNamespace(
                config=str(self.cfg_path),
                folder=ids,
                all=False,
                limit=limit,
                no_subtitles=False,
                no_llm=not with_llm,
            )
            ok = sync_mod.run(ns) == 0
        except Exception as e:
            self._log("error", f"同步异常: {e}")
        finally:
            self._sync_busy = False
            self.hub.put("sync_state", {"running": False, "ok": ok})
            self._log(
                "success" if ok else "error",
                "同步流程结束 ✔ 可以去「复习」页看看新卡片" if ok else "同步未完成，请查看上方日志",
            )

    def rpc_jobs(self) -> dict:
        """各后台任务的运行状态，页面切回来时用它恢复按钮态。"""
        return {
            "folders": self._folders_busy,
            "sync": self._sync_busy,
            "fill": self._fill_busy,
            "anki": self._anki_busy,
        }

    # ---------------------------------------------------------------- 卡片库

    def rpc_cards(self, flt: str = "全部") -> dict:
        today = date.today().isoformat()
        wanted = (flt or "全部").strip()
        counts = {k: 0 for k in CARD_FILTERS}
        items = []
        for r in self.store().all_cards():
            status = _card_status(r["reps"], r["due_date"], r["interval_days"], today)
            counts[status] = counts.get(status, 0) + 1
            if wanted != "全部" and status != wanted:
                continue
            items.append(_card_row(r, status))
        counts["全部"] = sum(counts.values())
        return {
            "items": items[:CARD_LIST_CAP],
            "counts": counts,
            "shown": min(len(items), CARD_LIST_CAP),
            "capped": len(items) > CARD_LIST_CAP,
        }

    def rpc_card_detail(self, bvid: str = "") -> dict:
        if not bvid:
            raise RuntimeError("缺少卡片 BV 号")
        st = self.store()
        row = st.get_video(bvid)
        if row is None:
            raise RuntimeError("没有找到这张卡片")
        state = st.get_review_state(bvid)
        merged = dict(row)
        merged["reps"] = (state["reps"] if state else 0) or 0
        merged["lapses"] = (state["lapses"] if state else 0) or 0
        payload = _card_payload(merged)
        card = _load_card(row)
        payload.update(
            {
                "status": _card_status(
                    merged["reps"],
                    state["due_date"] if state else None,
                    state["interval_days"] if state else None,
                    date.today().isoformat(),
                ),
                "due_date": state["due_date"] if state else None,
                "interval_days": state["interval_days"] if state else None,
                "intro": row["intro"] or "",
                "summary_source": str(card.get("source") or ""),
                "transcript_note": row["subtitle_note"] or "",
                "transcript_excerpt": (row["transcript"] or "")[:800],
            }
        )
        return payload

    def rpc_card_promote(self, bvid: str = "") -> dict:
        if not bvid:
            raise RuntimeError("缺少卡片 BV 号")
        st = self.store()
        if st.get_review_state(bvid) is None:
            raise RuntimeError("这张卡片还没进入复习排期")
        today = date.today().isoformat()
        st.set_due_date(bvid, today)
        self._log("info", f"已把卡片提前到今天复习：{bvid}")
        return {"ok": True, "due_date": today}

    def rpc_fill_start(self, limit: int = 100) -> dict:
        """补齐缺失摘要（只走本地库 + AI，不依赖登录态）。"""
        if self._fill_busy:
            return {"started": False, "error": "补齐摘要已经在进行中"}
        try:
            count = max(1, int(limit or 100))
        except (TypeError, ValueError):
            count = 100
        self._fill_busy = True
        self.hub.put("fill_state", {"running": True})
        self._log("rule", "🤖 补齐缺失摘要")
        self._log("info", "三档策略：有字幕精摘 → 无字幕批量轻摘（8条/次） → 无信息零AI兜底")
        self._log("info", "提示：轻摘卡之后会被 sync 拉到的字幕摘要自动覆盖升级")
        threading.Thread(target=self._fill_worker, args=(count,), daemon=True).start()
        return {"started": True}

    def _fill_worker(self, limit: int) -> None:
        from ..commands.sync import fill_summaries

        made = -1
        try:
            self.refresh_config()
            made = fill_summaries(self.store(), self.cfg, limit)
        except Exception as e:
            self._log("error", f"补齐异常: {e}")
        finally:
            self._fill_busy = False
            if made > 0:
                self._log("success", f"摘要补齐完成：本次新增 {made} 张；若还有缺漏，再点一次即可")
            elif made == 0:
                self._log("success", "没有需要补的摘要（全部齐了）✔")
            else:
                self._log("error", "补齐未完成，请查看上方日志")
            self.hub.put("fill_state", {"running": False, "made": made})

    def rpc_anki_start(self) -> dict:
        if self._anki_busy:
            return {"started": False, "error": "导出已经在进行中"}
        self._anki_busy = True
        self.hub.put("anki_state", {"running": True})
        self._log("rule", "📤 导出 Anki 牌组")
        threading.Thread(target=self._anki_worker, daemon=True).start()
        return {"started": True}

    def _anki_worker(self) -> None:
        from ..commands import anki_export

        ok = False
        try:
            ok = anki_export.run(
                SimpleNamespace(config=str(self.cfg_path), out=None, deck=None)
            ) == 0
        except Exception as e:
            self._log("error", f"导出异常: {e}")
        finally:
            self._anki_busy = False
            exports = resolve_data_dir(self.cfg) / "exports"
            self.hub.put("anki_state", {"running": False, "ok": ok, "dir": str(exports)})
            self._log("info" if ok else "error", f"文件位置: {exports}" if ok else "导出失败，请查看上方日志")

    # ---------------------------------------------------------------- 搜索与统计

    def rpc_search(self, query: str = "", limit: int = 20) -> dict:
        text = (query or "").strip()
        if not text:
            return {"items": [], "query": ""}
        try:
            top = max(1, min(200, int(limit or 20)))
        except (TypeError, ValueError):
            top = 20
        items = []
        for r in self.store().search(text, top):
            snip = (r["snip"] if "snip" in r.keys() and r["snip"] else None) or make_snippet(
                r, text
            )
            items.append(
                {
                    "bvid": r["bvid"],
                    "title": str(r["title"] or ""),
                    "upper": str(r["upper_name"] or ""),
                    "folder": str(r["folder_title"] or ""),
                    "snippet": " ".join(snip.split())[:200],
                }
            )
        self._log("info", f"搜索「{text}」命中 {len(items)} 条")
        return {"items": items, "query": text}

    def rpc_stats(self) -> dict:
        today = date.today().isoformat()
        st = self.store()
        overdue, due_series = st.due_by_day(today, days=7)
        activity = st.review_activity(days=14)
        due_new, due_old = st.due_breakdown(today)
        return {
            "counts": st.counts(),
            "lifetime": st.lifetime_stats(),
            "due": {"new": due_new, "old": due_old, "overdue": overdue},
            "due_series": [{"label": lbl, "value": n} for lbl, n in due_series],
            "activity": [{"label": lbl, "value": n} for lbl, n in activity],
            "reviewed_7d": sum(n for _, n in activity[-7:]),
        }

    # ---------------------------------------------------------------- 设置

    def rpc_settings_save(self, api_key: str = "", base_url: str = "", model: str = "") -> dict:
        config_mod.update_config_values(
            self.cfg_path,
            {
                "api_key": (api_key or "").strip(),
                "base_url": (base_url or "").strip(),
                "model": (model or "").strip(),
            },
        )
        self.refresh_config()
        self._log("success", "AI 配置已保存")
        return {"settings": self._settings_data()}

    def rpc_push_save(self, sendkey: str = "") -> dict:
        config_mod.update_config_values(
            self.cfg_path,
            {"serverchan_sendkey": (sendkey or "").strip()},
            insert_section="[notify]",
        )
        self.refresh_config()
        self._log("success", "推送配置已保存")
        return {"settings": self._settings_data()}

    def _settings_data(self) -> dict:
        llm = self.cfg.get("llm") or {}
        return {
            "api_key": llm.get("api_key", ""),
            "base_url": llm.get("base_url", ""),
            "model": llm.get("model", ""),
            "sendkey": (self.cfg.get("notify") or {}).get("serverchan_sendkey", ""),
            "config_path": str(self.cfg_path),
        }

    # ---------------------------------------------------------------- 提醒计划任务

    @staticmethod
    def _schtasks(*args: str):
        # schtasks 输出为控制台代码页（zh-CN 为 GBK），显式解码避免崩溃
        return subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            encoding="gbk",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _task_data(self) -> dict:
        r = self._schtasks("/Query", "/TN", TASK_NAME)
        return {"enabled": r.returncode == 0, "name": TASK_NAME}

    def rpc_task_status(self) -> dict:
        return self._task_data()

    def rpc_task_create(self, time: str = "09:30") -> dict:
        hhmm = _norm_hhmm(time)
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        runner = pyw if pyw.exists() else exe
        tr = f'"{runner}" -m bili_fav_review due --notify'
        r = self._schtasks(
            "/Create", "/F", "/SC", "DAILY", "/ST", hhmm, "/TN", TASK_NAME, "/TR", tr
        )
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "").strip()[:300]
            raise RuntimeError(detail or "创建计划任务失败")
        self._log("success", f"每日提醒已开启：每天 {hhmm} 弹出到期通知")
        return {"enabled": True, "time": hhmm}

    def rpc_task_remove(self) -> dict:
        r = self._schtasks("/Delete", "/TN", TASK_NAME, "/F")
        enabled = self._task_data()["enabled"]
        if r.returncode != 0:
            if enabled:  # 任务还在，说明删除失败（多半是权限），别报成功
                detail = (r.stderr or r.stdout or "").strip()[:300]
                raise RuntimeError(detail or "移除计划任务失败")
            return {"enabled": False, "removed": False}
        self._log("info", "每日提醒已移除")
        return {"enabled": enabled, "removed": True}

    # ---------------------------------------------------------------- 打开外部

    def rpc_open_path(self, kind: str = "data") -> dict:
        if kind == "data":
            path = resolve_data_dir(self.cfg)
            path.mkdir(parents=True, exist_ok=True)
        elif kind == "exports":
            path = resolve_data_dir(self.cfg) / "exports"
            path.mkdir(parents=True, exist_ok=True)
        elif kind == "guide":
            candidates = [
                Path(__file__).resolve().parent.parent.parent / "使用指南.md",
                Path.cwd() / "使用指南.md",
            ]
            found = next((p for p in candidates if p.exists()), None)
            if found is None:
                return {"ok": False, "error": "未找到《使用指南.md》（开源仓库里才有，安装分发不含）"}
            path = found
        else:
            raise RuntimeError(f"未知路径类型: {kind}")
        os.startfile(str(path))  # noqa: S606 — Windows 资源管理器/默认程序
        return {"ok": True, "path": str(path)}

    def rpc_open_url(self, url: str = "") -> dict:
        host = (urlsplit(url).hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in _EXTERNAL_HOSTS):
            raise RuntimeError("只允许打开 B 站链接")
        webbrowser.open(url)
        return {"ok": True}
