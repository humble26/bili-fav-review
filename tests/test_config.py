import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bili_fav_review.config import (
    DEFAULT_CONFIG,
    last_load_error,
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

    # ---- 配置文件损坏时的容错 ----
    # 回归：此前 tomllib.load 无 try 包裹，用户按帮助手工编辑 config.toml 写错引号，
    # 所有子命令与 GUI 都会抛 TOMLDecodeError 直接起不来（pythonw 下表现为「双击没反应」）。

    def test_broken_toml_does_not_raise_and_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[llm]\napi_key = "unclosed\n', encoding="utf-8")  # 引号未闭合
            cfg, used = load_config(str(p))  # 不得抛异常
            self.assertEqual(used, p)
            self.assertEqual(cfg["llm"]["api_key"], DEFAULT_CONFIG["llm"]["api_key"])

    def test_broken_toml_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("this is not toml = = =\n", encoding="utf-8")
            load_config(str(p))
            err = last_load_error()
            self.assertIsNotNone(err, "必须能被上层读到，否则就是静默回退")
            self.assertIn("语法错误", err)
            self.assertIn(str(p), err)

    def test_broken_toml_is_backed_up_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            original = '[llm]\napi_key = "unclosed\n'
            p.write_text(original, encoding="utf-8")
            load_config(str(p))
            backups = list(Path(d).glob("config.toml.broken-*"))
            self.assertEqual(len(backups), 1, "必须留下一份备份")
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original,
                             "备份内容必须与损坏原文逐字一致，不能丢用户内容")

    def test_valid_config_clears_previous_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "config.toml"
            bad.write_text("[[[\n", encoding="utf-8")
            load_config(str(bad))
            self.assertIsNotNone(last_load_error())

            good = Path(d) / "good.toml"
            good.write_text('[llm]\nmodel = "m"\n', encoding="utf-8")
            cfg, _ = load_config(str(good))
            self.assertIsNone(last_load_error(), "换到正常配置后错误状态必须清空")
            self.assertEqual(cfg["llm"]["model"], "m")

    def test_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d), mock.patch(
            "bili_fav_review.paths.default_data_dir", return_value=Path(d)
        ):
            load_config("/nonexistent/config.toml")
            self.assertIsNone(last_load_error(), "文件不存在属于正常情况，不应报错")

    def test_unreadable_config_falls_back(self):
        # 权限/IO 错误也不能让程序起不来
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[llm]\n", encoding="utf-8")
            with mock.patch("builtins.open", side_effect=OSError("爆了")):
                cfg, _ = load_config(str(p))
            self.assertEqual(cfg["llm"]["api_key"], DEFAULT_CONFIG["llm"]["api_key"])
            self.assertIn("无法读取", last_load_error() or "")

    # ------------------------------------------------------------------
    # 备份与上报的频次约束
    # load_config 会被频繁调用（Web 界面每次刷新都经 refresh_config 走一遍），
    # 所以「备份」与「上报」两件事都必须做频次约束，否则会堆文件、刷屏。
    # ------------------------------------------------------------------

    def test_same_broken_content_backed_up_only_once(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[llm]\napi_key = "unclosed\n', encoding="utf-8")
            # 让每次调用的时间戳都不同：按时间戳命名的话旧写法会造出 3 份
            stamps = [f"2026010{i}-120000" for i in (1, 2, 3)]
            with mock.patch("bili_fav_review.config.time.strftime",
                            side_effect=stamps):
                for _ in range(3):
                    load_config(str(p))
            backups = sorted(Path(d).glob("config.toml.broken-*"))
            self.assertEqual(
                len(backups), 1,
                f"同一份损坏内容只应留一份备份，实得：{[b.name for b in backups]}")

    def test_changed_broken_content_keeps_its_own_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[[[\n", encoding="utf-8")
            load_config(str(p))
            p.write_text("]]]\n", encoding="utf-8")
            load_config(str(p))
            backups = sorted(Path(d).glob("config.toml.broken-*"))
            self.assertEqual(len(backups), 2, "内容不同应各留一份，不能覆盖上一版")
            self.assertEqual(sorted(b.read_text(encoding="utf-8") for b in backups),
                             ["[[[\n", "]]]\n"])

    def test_webui_reports_config_error_only_once(self):
        """Web 界面每次刷新都会走 refresh_config —— 同一条只报一次，不能刷屏。"""
        from bili_fav_review.webui.api import Api

        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d), mock.patch(
            "bili_fav_review.paths.default_data_dir", return_value=Path(d)
        ):
            (Path(d) / "config.toml").write_text(
                '[llm]\napi_key = "unclosed\n', encoding="utf-8")
            api = Api()
            api.refresh_config()   # 模拟再刷新两次页面
            api.refresh_config()
            events = api.hub.since(0)["events"]
            errs = [e for e in events
                    if e["kind"] == "log" and e["data"].get("level") == "error"]
            self.assertEqual(len(errs), 1,
                             f"配置错误应只上报一次，实得 {len(errs)} 条")
            self.assertIn("语法错误", errs[0]["data"]["text"])


if __name__ == "__main__":
    unittest.main()
