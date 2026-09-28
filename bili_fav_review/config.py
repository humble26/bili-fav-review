"""配置加载：TOML 格式，查找顺序 --config 参数 > ./config.toml > ~/.bili_fav_review/config.toml"""

import copy
import shutil
import sys
import time
import tomllib
from pathlib import Path

from . import paths

# 最近一次 load_config 遇到的解析问题（None 表示正常）。
# 应用帮助里引导用户手工编辑 config.toml，写错引号/括号很常见；
# 此前会直接抛 TOMLDecodeError，pythonw 下界面根本不显示，用户看到的是「双击没反应」。
_LAST_LOAD_ERROR: str | None = None

# 已经打到 stderr 过的那条消息，避免 CLI 每个子命令重复刷屏
_LAST_PRINTED: str | None = None

DEFAULT_CONFIG = {
    "bilibili": {
        # 要同步的收藏夹 id 列表；留空则首次 sync 时交互选择（会记住选择）
        "folders": [],
        # 字幕优先级：优先真实 CC 字幕，其次 AI 字幕
        "subtitle_priority": ["zh-Hans", "ai-zh"],
    },
    "llm": {
        "enabled": True,
        # OpenAI 兼容接口均可：GLM / DeepSeek / Moonshot / ollama ...
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "model": "glm-4-flash",
        "max_transcript_chars": 9000,
        "timeout": 120,
        # 无字幕视频的批量轻摘：一次 AI 调用合并多少个视频（越大越省请求）
        "batch_intro_size": 8,
    },
    "review": {
        "new_due_days": 0,  # 新收藏当天即可学习（0=同步完就能在复习页看到）
        "max_per_session": 30,  # 单次复习最多过几张卡
    },
    "sync": {
        "videos_per_run": 40,  # 每次最多为新视频拉字幕的数量
        "summaries_per_run": 40,  # 每次最多调用 LLM 摘要的数量（控制花费）
        "request_interval": 1.0,  # B站 API 请求间隔（秒），别调太小
    },
    "notify": {
        # Server酱 SendKey（可选）：填入后每日提醒会把到期数量推送到微信
        "serverchan_sendkey": "",
    },
    "storage": {
        # 数据目录，留空使用 ~/.bili_fav_review
        "data_dir": "",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_candidates(explicit: str | None = None) -> list[Path]:
    out = []
    if explicit:
        out.append(Path(explicit).expanduser())
    out.append(Path("config.toml"))  # 项目目录下
    out.append(paths.default_data_dir() / "config.toml")
    return out


def _backup_broken(path: Path) -> Path | None:
    """把损坏的配置文件另存一份，绝不丢弃用户内容。返回备份路径。

    同一份损坏内容只备份一次：load_config 会被频繁调用（Web 界面每次刷新
    都会经 refresh_config 再走一遍），否则会堆出一串 .broken-* 文件。
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    # 已有内容相同的备份就直接复用（只比对最近 10 个，避免目录异常时全量扫描）
    for old in sorted(path.parent.glob(f"{path.name}.broken-*"), reverse=True)[:10]:
        try:
            if old.read_bytes() == raw:
                return old
        except OSError:
            continue
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.broken-{stamp}")
    n = 1
    while dest.exists():  # 同一秒内出现不同内容时不要互相覆盖
        n += 1
        dest = path.with_name(f"{path.name}.broken-{stamp}-{n}")
    try:
        shutil.copy2(path, dest)
        return dest
    except OSError:
        return None


def load_config(explicit: str | None = None) -> tuple[dict, Path | None]:
    """返回 (配置 dict, 实际使用的配置文件路径或 None)。

    解析失败时**不再抛异常**（那会让 GUI 彻底起不来），改为：
    备份损坏文件 → 回退默认配置 → 把原因记在 last_load_error() 里供上层展示。
    """
    global _LAST_LOAD_ERROR

    for p in config_candidates(explicit):
        if not p.exists():
            continue
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            backup = _backup_broken(p)
            hint = f"；原文件已备份为 {backup.name}" if backup else ""
            _LAST_LOAD_ERROR = (
                f"配置文件语法错误，已回退默认配置：{p}\n  {e}{hint}\n"
                f"  修好该文件后重启即可恢复你的设置。"
            )
            _report(_LAST_LOAD_ERROR)
            return copy.deepcopy(DEFAULT_CONFIG), p
        except OSError as e:
            _LAST_LOAD_ERROR = f"配置文件无法读取，已回退默认配置：{p}\n  {e}"
            _report(_LAST_LOAD_ERROR)
            return copy.deepcopy(DEFAULT_CONFIG), p

        _LAST_LOAD_ERROR = None
        return _merge(DEFAULT_CONFIG, data), p

    _LAST_LOAD_ERROR = None
    return copy.deepcopy(DEFAULT_CONFIG), None


def last_load_error() -> str | None:
    """最近一次 load_config 的失败原因；None 表示一切正常。

    调用方（GUI / CLI）应把它展示给用户 —— 静默回退默认配置本身就是一种故障，
    用户会以为自己的设置莫名其妙丢了。
    """
    return _LAST_LOAD_ERROR


def _report(err: str) -> None:
    """把配置问题打到 stderr（CLI 可见），同一条只打一次。"""
    global _LAST_PRINTED
    if err == _LAST_PRINTED:
        return
    _LAST_PRINTED = err
    print(f"[配置] {err}", file=sys.stderr, flush=True)


def validate_llm(cfg: dict) -> list[str]:
    """返回 LLM 配置的问题列表；空列表表示可用。"""
    problems = []
    llm = cfg.get("llm") or {}
    if llm.get("enabled", True):
        if not llm.get("api_key"):
            problems.append("llm.api_key 未配置（若暂时只想同步字幕不做摘要，可在 config.toml 设 llm.enabled = false）")
        if not llm.get("base_url"):
            problems.append("llm.base_url 未配置")
        if not llm.get("model"):
            problems.append("llm.model 未配置")
    return problems


def resolve_config_path(explicit: str | None = None) -> Path:
    """返回应读写的配置文件路径：优先已存在的，否则默认用户目录下的 config.toml。"""
    for p in config_candidates(explicit):
        if p.exists():
            return p
    return paths.default_data_dir() / "config.toml"


MINIMAL_CONFIG_TEMPLATE = """[bilibili]
folders = []
subtitle_priority = ["zh-Hans", "ai-zh"]

[llm]
enabled = true
base_url = "https://open.bigmodel.cn/api/paas/v4"
api_key = ""
model = "glm-4-flash"
max_transcript_chars = 9000
timeout = 120
batch_intro_size = 8

[review]
new_due_days = 0
max_per_session = 30

[sync]
videos_per_run = 40
summaries_per_run = 40
request_interval = 1.0

[notify]
serverchan_sendkey = ""

[storage]
data_dir = ""
"""


def update_config_values(path: Path, updates: dict, insert_section: str = "[llm]") -> Path:
    """把若干字符串型键值写进配置文件（行级替换；文件不存在则生成最小配置）。

    仅适用于全文件唯一的键；键缺失时插入到 insert_section 区块。
    """
    import re

    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = MINIMAL_CONFIG_TEMPLATE
    for key, value in updates.items():
        value = str(value).replace('"', '\\"')
        pat = re.compile(rf'(?m)^(\s*{re.escape(key)}\s*=\s*)"[^"]*"\s*(#.*)?$')
        if pat.search(text):
            text = pat.sub(lambda m: m.group(1) + f'"{value}"', text, count=1)
        elif insert_section in text:
            text = text.replace(insert_section, f"{insert_section}\n{key} = \"{value}\"", 1)
        else:
            text += f"\n{insert_section}\n{key} = \"{value}\"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
