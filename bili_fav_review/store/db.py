"""SQLite 存储层。

两张主表：videos（视频元数据+字幕+摘要）、review_state（遗忘曲线状态），
外加 FTS5 全文索引（trigram 分词，支持中文子串；建不出来时退回 LIKE 查询）
和 settings（键值配置，如收藏夹选择）。
"""

import json
import sqlite3
import time
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos(
    bvid TEXT PRIMARY KEY,
    aid INTEGER,
    cid INTEGER,
    title TEXT NOT NULL DEFAULT '',
    intro TEXT NOT NULL DEFAULT '',
    upper_name TEXT NOT NULL DEFAULT '',
    duration INTEGER NOT NULL DEFAULT 0,
    folder_id INTEGER,
    folder_title TEXT NOT NULL DEFAULT '',
    fav_time INTEGER,
    pubtime INTEGER,
    subtitle_lang TEXT,
    subtitle_checked INTEGER NOT NULL DEFAULT 0,
    subtitle_note TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    summary_json TEXT,
    summary_error TEXT,
    summary_error_at INTEGER,
    is_demo INTEGER NOT NULL DEFAULT 0,
    added_at INTEGER,
    synced_at INTEGER
);
CREATE TABLE IF NOT EXISTS review_state(
    bvid TEXT PRIMARY KEY REFERENCES videos(bvid) ON DELETE CASCADE,
    ease REAL NOT NULL DEFAULT 2.3,
    interval_days REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_date TEXT,
    last_review INTEGER,
    suspended INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5("
    "bvid UNINDEXED, title, intro, transcript, summary_text, tokenize='trigram')"
)

VIDEO_COLS = (
    "bvid, aid, cid, title, intro, upper_name, duration, folder_id, folder_title, "
    "fav_time, pubtime, subtitle_lang, subtitle_checked, subtitle_note, transcript, "
    "summary_json, summary_error, is_demo"
)


def make_snippet(row: sqlite3.Row, query: str, width: int = 80) -> str:
    """LIKE 查询结果没有 snippet，手动在字幕/简介里截一段。"""
    for field in ("transcript", "intro", "title"):
        text = row[field] or ""
        idx = text.find(query)
        if idx >= 0:
            start = max(0, idx - width // 2)
            return ("…" if start else "") + text[start : idx + width].replace("\n", " ") + "…"
    return (row["intro"] or row["title"] or "")[:width]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.fts_enabled = True
        try:
            self.conn.execute(FTS_SCHEMA)
        except sqlite3.OperationalError:
            self.fts_enabled = False  # 老版本 SQLite 无 trigram，退回 LIKE
        self.conn.commit()

    def backup(self, keep: int = 7) -> Path | None:
        """每日自动备份到数据目录 backups/ 下，保留最近 keep 份。当天已备份则只做裁剪。"""
        bdir = self.path.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y%m%d")
        dest = bdir / f"review-{today}.db"
        created = None
        if not dest.exists():
            tmp = bdir / f"review-{today}.tmp"
            dst = sqlite3.connect(str(tmp))
            try:
                self.conn.backup(dst)
            finally:
                dst.close()
            tmp.replace(dest)
            created = dest
        backups = sorted(bdir.glob("review-*.db"))
        for old in backups[:-keep] if keep else []:
            try:
                old.unlink()
            except OSError:
                pass
        return created

    def close(self) -> None:
        self.conn.close()

    # ---------- 视频元数据 ----------

    def upsert_video(self, v: dict) -> bool:
        """插入或更新收藏夹元数据；返回是否为新视频。"""
        exists = self.conn.execute(
            "SELECT 1 FROM videos WHERE bvid=?", (v["bvid"],)
        ).fetchone()
        self.conn.execute(
            """INSERT INTO videos(bvid, aid, cid, title, intro, upper_name, duration,
                 folder_id, folder_title, fav_time, pubtime, added_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(bvid) DO UPDATE SET
                 title=excluded.title, intro=excluded.intro,
                 upper_name=excluded.upper_name, duration=excluded.duration,
                 folder_id=excluded.folder_id, folder_title=excluded.folder_title,
                 fav_time=excluded.fav_time""",
            (
                v["bvid"], v.get("aid"), v.get("cid"), v.get("title", ""),
                v.get("intro", "") or "", v.get("upper_name", ""), v.get("duration", 0),
                v.get("folder_id"), v.get("folder_title", ""), v.get("fav_time"),
                v.get("pubtime"), int(time.time()),
            ),
        )
        self.conn.commit()
        return exists is None

    def get_video(self, bvid: str) -> sqlite3.Row | None:
        return self.conn.execute(
            f"SELECT {VIDEO_COLS} FROM videos WHERE bvid=?", (bvid,)
        ).fetchone()

    def videos_needing_transcript(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            f"SELECT {VIDEO_COLS} FROM videos WHERE is_demo=0 AND subtitle_checked=0 "
            "AND transcript='' ORDER BY fav_time DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def save_transcript(self, bvid: str, cid: int, lang: str, text: str) -> None:
        self.conn.execute(
            "UPDATE videos SET cid=?, subtitle_lang=?, subtitle_checked=1, "
            "subtitle_note='', transcript=?, synced_at=? WHERE bvid=?",
            (cid, lang, text, int(time.time()), bvid),
        )
        self.conn.commit()
        self.reindex(bvid)

    def mark_subtitle_checked(self, bvid: str, note: str) -> None:
        """该视频查过且没有可用字幕（或查询失败），记备注避免反复重试。"""
        self.conn.execute(
            "UPDATE videos SET subtitle_checked=1, subtitle_note=?, synced_at=? WHERE bvid=?",
            (note, int(time.time()), bvid),
        )
        self.conn.commit()

    def videos_needing_summary(
        self, limit: int, retry_after: int = 86400, mode: str = "full"
    ) -> list[sqlite3.Row]:
        """待摘要视频。

        mode="full"  → 有字幕全文的（单条精摘）；
        mode="intro" → 无字幕全文的（用标题+简介批量轻摘，含尚未检查过字幕的——
                       乐观生成，之后 sync 若拉到字幕会自动覆盖升级为精摘卡）。
        """
        cutoff = int(time.time()) - retry_after
        cond = "transcript != ''" if mode == "full" else "transcript = ''"
        return self.conn.execute(
            f"SELECT {VIDEO_COLS} FROM videos WHERE is_demo=0 AND summary_json IS NULL "
            f"AND {cond} AND (summary_error IS NULL OR summary_error_at <= ?) "
            "ORDER BY fav_time DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()

    def save_summary(self, bvid: str, summary: dict) -> None:
        self.conn.execute(
            "UPDATE videos SET summary_json=?, summary_error=NULL, summary_error_at=NULL WHERE bvid=?",
            (json.dumps(summary, ensure_ascii=False), bvid),
        )
        self.conn.commit()
        self.reindex(bvid)

    def mark_summary_error(self, bvid: str, err: str) -> None:
        self.conn.execute(
            "UPDATE videos SET summary_error=?, summary_error_at=? WHERE bvid=?",
            (err[:300], int(time.time()), bvid),
        )
        self.conn.commit()

    # ---------- FTS ----------

    def _summary_text(self, row: sqlite3.Row) -> str:
        if not row["summary_json"]:
            return ""
        try:
            s = json.loads(row["summary_json"])
        except Exception:
            return ""
        if not isinstance(s, dict):  # 畸形摘要别把 FTS 索引写挂了
            return ""
        parts = [s.get("one_liner") or ""]
        parts += list(s.get("key_points") or [])
        parts += list(s.get("keywords") or [])
        for q in s.get("quiz") or []:
            if isinstance(q, dict):
                parts.append(q.get("question") or "")
                parts.append(q.get("answer") or "")
        return " ".join(str(p) for p in parts if p)

    def reindex(self, bvid: str) -> None:
        if not self.fts_enabled:
            return
        row = self.get_video(bvid)
        if row is None:
            return
        self.conn.execute(
            "DELETE FROM videos_fts WHERE rowid IN "
            "(SELECT rowid FROM videos_fts WHERE bvid=?)",
            (bvid,),
        )
        self.conn.execute(
            "INSERT INTO videos_fts(bvid, title, intro, transcript, summary_text) VALUES(?,?,?,?,?)",
            (bvid, row["title"], row["intro"], row["transcript"], self._summary_text(row)),
        )
        self.conn.commit()

    def search(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        query = (query or "").strip()
        if not query:
            return []
        if self.fts_enabled and len(query) >= 3:
            try:
                terms = " ".join(
                    '"%s"' % t.replace('"', '""') for t in query.split() if t
                )
                rows = self.conn.execute(
                    "SELECT v.*, snippet(videos_fts, -1, '«', '»', '…', 12) AS snip "
                    "FROM videos_fts f JOIN videos v ON v.bvid = f.bvid "
                    "WHERE videos_fts MATCH ? ORDER BY rank LIMIT ?",
                    (terms, limit),
                ).fetchall()
                if rows:
                    return rows
            except sqlite3.OperationalError:
                pass  # 查询语法问题则走 LIKE
        like = f"%{query}%"
        return self.conn.execute(
            "SELECT *, NULL AS snip FROM videos WHERE title LIKE ? OR intro LIKE ? "
            "OR transcript LIKE ? OR summary_json LIKE ? LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()

    # ---------- 遗忘曲线 ----------

    def init_review(self, bvid: str, due_date: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO review_state(bvid, due_date) VALUES(?,?)",
            (bvid, due_date),
        )
        self.conn.commit()

    def get_review_state(self, bvid: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_state WHERE bvid=?", (bvid,)
        ).fetchone()

    def save_review_state(self, bvid: str, st: dict, suspended: bool | None = None) -> None:
        self.conn.execute(
            """INSERT INTO review_state(bvid, ease, interval_days, reps, lapses, due_date, last_review, suspended)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(bvid) DO UPDATE SET ease=excluded.ease,
                 interval_days=excluded.interval_days, reps=excluded.reps,
                 lapses=excluded.lapses, due_date=excluded.due_date,
                 last_review=excluded.last_review,
                 suspended=COALESCE(?, review_state.suspended)""",
            (
                bvid, st["ease"], st["interval_days"], st["reps"], st["lapses"],
                st["due_date"], st.get("last_review"), 1 if suspended else 0, suspended,
            ),
        )
        self.conn.commit()

    def due_items(self, today_iso: str, limit: int = 30) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT v.*, s.due_date, s.reps, s.lapses, s.ease, s.interval_days
                FROM review_state s JOIN videos v ON v.bvid = s.bvid
                WHERE s.due_date <= ? AND s.suspended=0
                ORDER BY s.due_date, s.reps LIMIT ?""",
            (today_iso, limit),
        ).fetchall()

    def due_count(self, today_iso: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM review_state WHERE due_date<=? AND suspended=0",
            (today_iso,),
        ).fetchone()[0]

    def due_breakdown(self, today_iso: str) -> tuple[int, int]:
        """返回 (新卡数, 复习卡数)——都指今日到期。"""
        row = self.conn.execute(
            """SELECT
                 SUM(CASE WHEN reps=0 THEN 1 ELSE 0 END),
                 SUM(CASE WHEN reps>0 THEN 1 ELSE 0 END)
               FROM review_state WHERE due_date<=? AND suspended=0""",
            (today_iso,),
        ).fetchone()
        return (row[0] or 0, row[1] or 0)

    def promotable_count(self, today_iso: str) -> int:
        """还没学过（reps=0）但排在今天之后的新卡数量。"""
        return self.conn.execute(
            "SELECT COUNT(*) FROM review_state WHERE reps=0 AND due_date>? AND suspended=0",
            (today_iso,),
        ).fetchone()[0]

    def promote_new_cards(self, today_iso: str) -> int:
        """把所有排在未来的新卡提前到今天，返回移动张数。"""
        cur = self.conn.execute(
            "UPDATE review_state SET due_date=? WHERE reps=0 AND due_date>? AND suspended=0",
            (today_iso, today_iso),
        )
        self.conn.commit()
        return cur.rowcount

    def set_due_date(self, bvid: str, due_iso: str) -> None:
        self.conn.execute(
            "UPDATE review_state SET due_date=? WHERE bvid=?", (due_iso, bvid)
        )
        self.conn.commit()

    def all_cards(self) -> list[sqlite3.Row]:
        """卡片库全量列表：新卡在前，其余按到期日升序。"""
        return self.conn.execute(
            """SELECT v.bvid, v.title, v.upper_name, v.folder_title,
                      v.summary_json, v.transcript,
                      s.due_date, s.reps, s.lapses, s.interval_days
               FROM videos v LEFT JOIN review_state s ON s.bvid = v.bvid
               ORDER BY CASE WHEN s.reps IS NULL OR s.reps = 0 THEN 0 ELSE 1 END,
                        CASE WHEN s.due_date IS NULL THEN 1 ELSE 0 END,
                        s.due_date,
                        v.fav_time DESC"""
        ).fetchall()

    def next_due_date(self) -> str | None:
        row = self.conn.execute(
            "SELECT MIN(due_date) FROM review_state WHERE due_date > date('now') AND suspended=0"
        ).fetchone()
        return row[0]

    def due_histogram(self, today_iso: str, days: int = 7) -> list[tuple[str, int]]:
        """未来 days 天的到期分布；窗口末端以传入的 today_iso 为基准（同 due_by_day）。"""
        end = (_date.fromisoformat(today_iso) + _timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT due_date, COUNT(*) FROM review_state WHERE suspended=0 AND due_date<=? GROUP BY due_date ORDER BY due_date",
            (end,),
        ).fetchall()
        out, overdue = [], 0
        for r in rows:
            if r["due_date"] < today_iso:
                overdue += r[1]
            else:
                out.append((r["due_date"], r[1]))
        if overdue:
            out.insert(0, ("已逾期", overdue))
        return out

    def lifetime_stats(self) -> dict:
        """累计统计：忘过总次数、平均记忆间隔。"""
        r = self.conn.execute(
            "SELECT COALESCE(SUM(lapses),0), COALESCE(AVG(interval_days),0) FROM review_state"
        ).fetchone()
        return {"lapses": int(r[0]), "avg_interval": round(float(r[1]), 1)}

    def due_by_day(self, today_iso: str, days: int = 7) -> tuple[int, list[tuple[str, int]]]:
        """返回 (已逾期数, 未来 days 天的逐日到期数 [(MM-DD, 数量)])。

        ⚠ 窗口末端与日期标签都以传入的 today_iso 为基准。
        此前这两处用的是 time.time()，导致 today_iso 只影响逾期计数、
        与返回的日期标签口径不一致（该函数也因此无法被测试）。
        生产调用点传的都是 date.today()，所以本修正对实际行为等价。
        """
        base = _date.fromisoformat(today_iso)
        end_iso = (base + _timedelta(days=days)).isoformat()
        overdue = self.conn.execute(
            "SELECT COUNT(*) FROM review_state WHERE due_date<? AND suspended=0",
            (today_iso,),
        ).fetchone()[0]
        rows = self.conn.execute(
            "SELECT due_date, COUNT(*) FROM review_state "
            "WHERE due_date>=? AND due_date<=? AND suspended=0 GROUP BY due_date",
            (today_iso, end_iso),
        ).fetchall()
        m = {r["due_date"]: r[1] for r in rows}
        out = []
        for i in range(days):
            d = base + _timedelta(days=i)
            out.append((d.strftime("%m-%d"), m.get(d.isoformat(), 0)))
        return overdue, out

    def review_activity(self, days: int = 14,
                        today_iso: str | None = None) -> list[tuple[str, int]]:
        """近 days 天的每日复习卡片数 [(MM-DD, 数量)]，按 last_review 记录统计。

        today_iso 可选：传了就以它为「今天」（便于测试），不传用系统当天。
        """
        base = _date.fromisoformat(today_iso) if today_iso else _date.today()
        start_int = int((base - _timedelta(days=days - 1)).strftime("%Y%m%d"))
        rows = {
            r[0]: r[1]
            for r in self.conn.execute(
                "SELECT last_review, COUNT(*) FROM review_state "
                "WHERE last_review>=? GROUP BY last_review",
                (start_int,),
            ).fetchall()
        }
        out = []
        for i in range(days):
            d = base - _timedelta(days=days - 1 - i)
            out.append((d.strftime("%m-%d"), rows.get(int(d.strftime("%Y%m%d")), 0)))
        return out

    def anki_cards(self) -> list[sqlite3.Row]:
        """导出 Anki 用的全部已摘要卡片。"""
        return self.conn.execute(
            "SELECT bvid, title, upper_name, folder_title, summary_json FROM videos "
            "WHERE is_demo=0 AND summary_json IS NOT NULL ORDER BY fav_time DESC"
        ).fetchall()

    # ---------- 统计与设置 ----------

    def counts(self) -> dict:
        c = self.conn
        one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "total": one("SELECT COUNT(*) FROM videos"),
            "with_transcript": one("SELECT COUNT(*) FROM videos WHERE transcript!=''"),
            "with_summary": one("SELECT COUNT(*) FROM videos WHERE summary_json IS NOT NULL"),
            "learning": one("SELECT COUNT(*) FROM review_state"),
            "mature": one("SELECT COUNT(*) FROM review_state WHERE interval_days>=21"),
        }

    def setting_get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def setting_set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    # ---------- demo 数据 ----------

    def insert_demo_video(self, v: dict) -> None:
        data = {
            "bvid": v["bvid"],
            "aid": v.get("aid"),
            "title": v.get("title", ""),
            "intro": v.get("intro", ""),
            "upper_name": v.get("upper_name", ""),
            "duration": v.get("duration", 0),
            "folder_id": v.get("folder_id"),
            "folder_title": v.get("folder_title", "演示收藏夹"),
            "fav_time": v.get("fav_time"),
            "pubtime": v.get("pubtime"),
            "subtitle_lang": v.get("subtitle_lang"),
            "transcript": v.get("transcript", ""),
            "summary_json": v.get("summary_json"),
            "is_demo": 1,
            "added_at": v.get("added_at") or int(time.time()),
        }
        self.conn.execute(
            """INSERT INTO videos(bvid, aid, title, intro, upper_name, duration,
                 folder_id, folder_title, fav_time, pubtime, subtitle_lang,
                 subtitle_checked, transcript, summary_json, is_demo, added_at)
               VALUES(:bvid,:aid,:title,:intro,:upper_name,:duration,:folder_id,
                 :folder_title,:fav_time,:pubtime,:subtitle_lang,1,:transcript,
                 :summary_json,:is_demo,:added_at)
               ON CONFLICT(bvid) DO UPDATE SET is_demo=1""",
            data,
        )
        self.conn.commit()

    def clear_demo(self) -> int:
        cur = self.conn.execute(
            "DELETE FROM review_state WHERE bvid IN (SELECT bvid FROM videos WHERE is_demo=1)"
        )
        cur2 = self.conn.execute("DELETE FROM videos WHERE is_demo=1")
        if self.fts_enabled:
            self.conn.execute("DELETE FROM videos_fts")
        self.conn.commit()
        return cur.rowcount + cur2.rowcount
