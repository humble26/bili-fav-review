import json
import tempfile
import unittest
from pathlib import Path

from bili_fav_review.store import Store
from bili_fav_review.store.srs import GRADE_OK, apply_review, new_state
from bili_fav_review.store.db import make_snippet


def _video(bvid, title="标题", transcript="", summary=None, intro=""):
    return {
        "bvid": bvid,
        "aid": 1,
        "cid": None,
        "title": title,
        "intro": intro,
        "upper_name": "UP主",
        "duration": 100,
        "folder_id": 1,
        "folder_title": "默认收藏夹",
        "fav_time": 1757400000,
        "pubtime": 1757300000,
    }


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_and_new_flag(self):
        self.assertTrue(self.store.upsert_video(_video("BV1a")))
        self.assertFalse(self.store.upsert_video(_video("BV1a", title="新标题")))
        self.assertEqual(self.store.get_video("BV1a")["title"], "新标题")

    def test_transcript_flow(self):
        self.store.upsert_video(_video("BV1b"))
        self.assertEqual(len(self.store.videos_needing_transcript(10)), 1)
        self.store.mark_subtitle_checked("BV1b", "无CC/AI字幕")
        self.assertEqual(len(self.store.videos_needing_transcript(10)), 0)

        self.store.upsert_video(_video("BV1c"))
        self.store.save_transcript("BV1c", 999, "zh-Hans", "[00:01] 你好世界")
        v = self.store.get_video("BV1c")
        self.assertEqual(v["subtitle_lang"], "zh-Hans")
        self.assertEqual(v["cid"], 999)
        self.assertEqual(len(self.store.videos_needing_transcript(10)), 0)
        self.assertEqual(len(self.store.videos_needing_summary(10)), 1)

    def test_summary_flow_and_retry_window(self):
        self.store.upsert_video(_video("BV1d"))
        self.store.save_transcript("BV1d", 1, "ai-zh", "文本")
        self.store.mark_summary_error("BV1d", " boom ")
        # 24h 重试窗口内不会重试
        self.assertEqual(len(self.store.videos_needing_summary(10)), 0)
        self.assertEqual(len(self.store.videos_needing_summary(10, retry_after=0)), 1)
        self.store.save_summary("BV1d", {"one_liner": "ok", "key_points": [], "keywords": [], "quiz": []})
        self.assertEqual(len(self.store.videos_needing_summary(10, retry_after=0)), 0)

    def test_search_like_and_fts(self):
        self.store.upsert_video(_video("BV1e", title="机器学习入门", intro="梯度下降"))
        self.store.reindex("BV1e")
        self.store.save_transcript("BV1e", 1, "zh-Hans", "神经网络反向传播算法详解")
        for q in ("机器", "梯度", "反向传播", "神经网络"):
            rows = self.store.search(q)
            self.assertTrue(rows, f"搜索 {q} 应有结果")
            self.assertEqual(rows[0]["bvid"], "BV1e")
        self.assertEqual(self.store.search("不存在的词xyz"), [])

    def test_review_state(self):
        from datetime import date

        self.store.upsert_video(_video("BV1f"))
        self.store.init_review("BV1f", "2026-09-14")
        row = self.store.get_review_state("BV1f")
        self.assertEqual(row["due_date"], "2026-09-14")
        self.assertEqual(len(self.store.due_items("2026-09-14", 10)), 1)

        st = apply_review(dict(row), GRADE_OK, date(2026, 9, 13))
        self.store.save_review_state("BV1f", st)
        self.assertEqual(self.store.due_count("2026-09-13"), 0)
        self.assertEqual(self.store.due_count("2026-09-15"), 1)

    def test_due_breakdown_and_promote(self):
        from datetime import date

        # 新卡1 今天到期，新卡2 排在明天，老卡 已复习且未到期
        self.store.upsert_video(_video("BVn1"))
        self.store.init_review("BVn1", "2026-09-13")
        self.store.upsert_video(_video("BVn2"))
        self.store.init_review("BVn2", "2026-09-14")
        self.store.upsert_video(_video("BVo1"))
        self.store.init_review("BVo1", "2026-09-20")
        self.store.save_review_state(
            "BVo1",
            apply_review(new_state("2026-09-20"), GRADE_OK, date(2026, 9, 13)),
        )

        new_n, old_n = self.store.due_breakdown("2026-09-13")
        self.assertEqual((new_n, old_n), (1, 0))
        self.assertEqual(self.store.promotable_count("2026-09-13"), 1)  # 只有 BVn2

        moved = self.store.promote_new_cards("2026-09-13")
        self.assertEqual(moved, 1)
        self.assertEqual(self.store.due_count("2026-09-13"), 2)
        self.assertEqual(self.store.promotable_count("2026-09-13"), 0)

    def test_backup(self):
        self.store.upsert_video(_video("BVb"))
        p = self.store.backup(keep=2)
        self.assertIsNotNone(p)
        self.assertTrue(p.exists())
        # 同一天再备份：跳过
        self.assertIsNone(self.store.backup(keep=2))
        # keep 裁剪：伪造 8 个旧备份，保留最近 2 个
        bdir = p.parent
        for i in range(1, 9):
            (bdir / f"review-2026090{i}.db").write_bytes(b"x")
        self.store.backup(keep=2)
        left = sorted(x.name for x in bdir.glob("review-*.db"))
        self.assertEqual(len(left), 2)
        self.assertIn(p.name, left)

    def test_due_by_day_and_activity(self):
        import json as _json
        from datetime import date

        self.store.upsert_video(_video("BVd1"))
        self.store.init_review("BVd1", "2026-09-13")  # 今天
        self.store.upsert_video(_video("BVd2"))
        self.store.init_review("BVd2", "2026-09-10")  # 逾期
        overdue, series = self.store.due_by_day("2026-09-13", days=7)
        self.assertEqual(overdue, 1)
        self.assertEqual(series[0], ("09-13", 1))
        self.assertEqual(sum(n for _, n in series), 1)

        # 复习一次，产生 last_review 记录（今天=20260913）
        st = apply_review(new_state("2026-09-14"), GRADE_OK, date(2026, 9, 13))
        self.store.save_review_state("BVd1", st)
        act = self.store.review_activity(days=3)
        self.assertEqual(act[-1], ("09-13", 1))
        self.assertEqual(sum(n for _, n in act), 1)
        self.assertIsInstance(_json.dumps(act), str)

    def test_anki_cards(self):
        self.store.upsert_video(_video("BVa1"))
        self.store.save_summary("BVa1", {"one_liner": "x", "key_points": [], "keywords": [], "quiz": []})
        self.store.upsert_video(_video("BVa2"))  # 无摘要，不导出
        rows = self.store.anki_cards()
        self.assertEqual([r["bvid"] for r in rows], ["BVa1"])

    def test_all_cards_and_set_due_date(self):
        from datetime import date

        self.store.upsert_video(_video("BVc1", title="甲"))
        self.store.init_review("BVc1", "2026-09-20")
        self.store.upsert_video(_video("BVc2", title="乙"))
        self.store.init_review("BVc2", "2026-09-14")
        self.store.save_review_state(
            "BVc2", apply_review(new_state("2026-09-14"), GRADE_OK, date(2026, 9, 13))
        )

        rows = self.store.all_cards()
        self.assertEqual(len(rows), 2)
        # 新卡（reps=0）排前面
        self.assertEqual(rows[0]["bvid"], "BVc1")
        self.assertEqual(rows[0]["reps"], 0)

        self.store.set_due_date("BVc1", "2026-09-13")
        self.assertEqual(self.store.get_review_state("BVc1")["due_date"], "2026-09-13")
        # BVc1 提前到 09-13，BVc2 首次复习后到期 09-15
        self.assertEqual(self.store.due_count("2026-09-15"), 2)

    def test_settings_and_demo(self):
        self.store.setting_set("folders", [1, 2, 3])
        self.assertEqual(self.store.setting_get("folders"), [1, 2, 3])
        self.assertIsNone(self.store.setting_get("nothing"))

        v = _video("BVdemo")
        v.update({"is_demo": 1, "summary_json": json.dumps({"one_liner": "x"}), "added_at": 1})
        self.store.insert_demo_video(v)
        self.assertEqual(self.store.counts()["total"], 1)
        self.store.clear_demo()
        self.assertEqual(self.store.counts()["total"], 0)

    def test_make_snippet(self):
        row = {
            "transcript": "[00:01] 前缀无关内容 " * 3 + "目标关键词在后半部分",
            "intro": "简介",
            "title": "标题",
        }
        snip = make_snippet(row, "目标关键词")
        self.assertIn("目标关键词", snip)


if __name__ == "__main__":
    unittest.main()
