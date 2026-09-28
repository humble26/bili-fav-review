"""配置加载：TOML 格式，查找顺序 --config 参数 > ./config.toml > ~/.bili_fav_review/config.toml"""

import copy
import tomllib
from pathlib import Path

from . import paths

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


def load_config(explicit: str | None = None) -> tuple[dict, Path | None]:
    """返回 (配置 dict, 实际使用的配置文件路径或 None)。"""
    for p in config_candidates(explicit):
        if p.exists():
            with open(p, "rb") as f:
                data = tomllib.load(f)
            return _merge(DEFAULT_CONFIG, data), p
    return copy.deepcopy(DEFAULT_CONFIG), None


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
