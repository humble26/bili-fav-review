import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bili_fav_review.config import (
    DEFAULT_CONFIG,
    load_config,
    resolve_config_path,
    update_config_values,
    validate_llm,
)


class TestConfig(unittest.TestCase):
    def test_load_without_file_gives_defaults(self):
        # 隔离 CWD 与"用户目录"，避免被真实安装产生的 config.toml 干扰
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d), mock.patch(
            "bili_fav_review.paths.default_data_dir", return_value=Path(d)
        ):
            cfg, path = load_config("/nonexistent/config.toml")
            self.assertIsNone(path)
            self.assertEqual(cfg["bilibili"]["subtitle_priority"], ["zh-Hans", "ai-zh"])

    def test_load_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(
                '[llm]\nmodel = "my-model"\napi_key = "sk-test"\n'
                '[bilibili]\nfolders = [123]\n',
                encoding="utf-8",
            )
            cfg, used = load_config(str(p))
            self.assertEqual(used, p)
            self.assertEqual(cfg["llm"]["model"], "my-model")
            self.assertEqual(cfg["llm"]["base_url"], DEFAULT_CONFIG["llm"]["base_url"])
            self.assertEqual(cfg["bilibili"]["folders"], [123])
            self.assertEqual(cfg["sync"]["request_interval"], 1.0)

    def test_validate_llm(self):
        cfg = {"llm": {"enabled": True, "api_key": "", "base_url": "x", "model": "m"}}
        self.assertTrue(validate_llm(cfg))
        cfg["llm"]["api_key"] = "k"
        self.assertEqual(validate_llm(cfg), [])
        cfg["llm"]["enabled"] = False
        cfg["llm"]["api_key"] = ""
        self.assertEqual(validate_llm(cfg), [])

    def test_update_config_values_creates_minimal(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            update_config_values(p, {"api_key": "sk-abc"})
            cfg, _ = load_config(str(p))
            self.assertEqual(cfg["llm"]["api_key"], "sk-abc")
            self.assertEqual(cfg["llm"]["model"], "glm-4-flash")  # 模板其余键保留

    def test_update_config_values_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[llm]\napi_key = "old"  # 注释\nmodel = "m1"\n', encoding="utf-8")
            update_config_values(p, {"api_key": "new", "model": "m2"})
            text = p.read_text(encoding="utf-8")
            self.assertIn('api_key = "new"', text)
            self.assertNotIn("old", text)
            cfg, _ = load_config(str(p))
            self.assertEqual(cfg["llm"]["model"], "m2")

    def test_update_config_values_inserts_missing_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[bilibili]\nfolders = []\n", encoding="utf-8")
            update_config_values(p, {"api_key": "k1"})
            cfg, _ = load_config(str(p))
            self.assertEqual(cfg["llm"]["api_key"], "k1")

    def test_update_config_values_insert_section(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[llm]\napi_key = "k"\n', encoding="utf-8")
            update_config_values(p, {"serverchan_sendkey": "SCT1"}, insert_section="[notify]")
            cfg, _ = load_config(str(p))
            self.assertEqual(cfg["notify"]["serverchan_sendkey"], "SCT1")
            self.assertEqual(cfg["llm"]["api_key"], "k")

    def test_resolve_config_path(self):
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d), mock.patch(
            "bili_fav_review.paths.default_data_dir", return_value=Path(d)
        ):
            self.assertEqual(resolve_config_path("/nonexistent"), Path(d) / "config.toml")
            custom = Path(d) / "custom.toml"
            custom.write_text("", encoding="utf-8")
            self.assertEqual(resolve_config_path(str(custom)), custom)


if __name__ == "__main__":
    unittest.main()
