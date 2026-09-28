import unittest

from bili_fav_review.bilibili.wbi import MIXIN_KEY_ENC_TAB, get_mixin_key, sign_params
from bili_fav_review.summarize import _extract_json, _normalize, _truncate


IMG_KEY = "7cd084941338484aae1ad9425b94eeb9"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"


class TestWbi(unittest.TestCase):
    def test_mixin_tab_is_permutation(self):
        self.assertEqual(len(MIXIN_KEY_ENC_TAB), 64)
        self.assertEqual(sorted(MIXIN_KEY_ENC_TAB), list(range(64)))

    def test_mixin_key_length(self):
        key = get_mixin_key(IMG_KEY + SUB_KEY)
        self.assertEqual(len(key), 32)

    def test_sign_params_deterministic(self):
        base = {"bvid": "BV1xx", "cid": 123, "foo": "一'()*"}
        a = sign_params(base, IMG_KEY, SUB_KEY, now=1700000000)
        b = sign_params(base, IMG_KEY, SUB_KEY, now=1700000000)
        self.assertEqual(a, b)
        self.assertIn("wts", a)
        self.assertEqual(len(a["w_rid"]), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in a["w_rid"]))
        self.assertEqual(a["foo"], "一")  # 风控过滤字符被移除

    def test_sign_changes_with_params(self):
        a = sign_params({"x": 1}, IMG_KEY, SUB_KEY, now=1)
        b = sign_params({"x": 2}, IMG_KEY, SUB_KEY, now=1)
        self.assertNotEqual(a["w_rid"], b["w_rid"])


class TestSummarizeHelpers(unittest.TestCase):
    def test_extract_json_plain(self):
        self.assertEqual(_extract_json('{"a": 1}'), {"a": 1})

    def test_extract_json_fenced(self):
        text = "好的，以下是结果：\n```json\n{\"one_liner\": \"测试\"}\n```\n"
        self.assertEqual(_extract_json(text), {"one_liner": "测试"})

    def test_extract_json_with_preamble(self):
        text = '说明文字 {"a": {"b": 2}} 结尾'
        self.assertEqual(_extract_json(text), {"a": {"b": 2}})

    def test_extract_json_invalid(self):
        self.assertIsNone(_extract_json("完全没有 JSON"))

    def test_normalize(self):
        out = _normalize(
            {
                "one_liner": " 概括 ",
                "key_points": ["a", "", 123],
                "keywords": ["k1", "k2"],
                "quiz": [{"question": "Q?", "answer": "A"}, {"bad": 1}, "不是dict"],
            }
        )
        self.assertEqual(out["one_liner"], "概括")
        self.assertEqual(out["key_points"], ["a", "123"])
        self.assertEqual(out["quiz"], [{"question": "Q?", "answer": "A"}])

    def test_truncate(self):
        self.assertEqual(_truncate("abc", 10), "abc")
        t = _truncate("x" * 100 + "y" * 100, 40)
        self.assertLessEqual(len(t), 42)
        self.assertIn("省略", t)


if __name__ == "__main__":
    unittest.main()
