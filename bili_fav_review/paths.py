"""数据文件路径管理。所有用户数据默认放在 ~/.bili_fav_review/ 下。"""

from pathlib import Path

APP_DIR_NAME = ".bili_fav_review"


def default_data_dir() -> Path:
    return Path.home() / APP_DIR_NAME


def resolve_data_dir(cfg: dict) -> Path:
    raw = (cfg.get("storage") or {}).get("data_dir") or ""
    return Path(raw).expanduser() if raw else default_data_dir()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path(cfg: dict) -> Path:
    return ensure_dir(resolve_data_dir(cfg)) / "review.db"


def cookies_path(cfg: dict) -> Path:
    return ensure_dir(resolve_data_dir(cfg)) / "cookies.json"
