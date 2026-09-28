"""B 站扫码登录：生成二维码 → 轮询确认 → 保存 cookie 到本地文件。

cookie 等同于登录凭证，只保存在本机 ~/.bili_fav_review/cookies.json，
请勿提交到任何仓库或分享给他人。
"""

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

from ..ui import error, info, success, warn

PASSPORT = "https://passport.bilibili.com"
FINGER_SPI = "https://api.bilibili.com/x/frontend/finger/spi"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

# 需要持久化的 cookie 名单
COOKIE_KEYS = [
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "buvid3",
    "buvid4",
    "ac_time_value",
    "sid",
]


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _ensure_buvid(session: requests.Session) -> None:
    """领取 buvid3/buvid4，降低风控概率。"""
    try:
        r = session.get(FINGER_SPI, timeout=15)
        data = r.json().get("data") or {}
        if data.get("b_3"):
            session.cookies.set("buvid3", data["b_3"], domain=".bilibili.com")
        if data.get("b_4"):
            session.cookies.set("buvid4", data["b_4"], domain=".bilibili.com")
    except Exception:
        pass  # 拿不到 buvid 不阻塞登录，只影响风控概率


def _print_qr(url: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        warn("终端二维码渲染失败，请用下面这条链接生成二维码后用 B 站 App 扫码：")
        info(url)


def qr_login(
    poll_timeout: int = 180,
    render_qr=None,
    on_status=None,
    should_cancel=None,
) -> dict:
    """完成扫码登录，返回可持久化的 cookie dict。失败抛 RuntimeError。

    render_qr(url): 自定义二维码渲染回调（GUI 传入；缺省在终端打印二维码）
    on_status(text): 扫码状态回调（已扫码/待确认等；缺省打印到终端）
    should_cancel(): 返回 True 时中止登录（GUI 取消按钮用）
    """
    session = _new_session()
    _ensure_buvid(session)

    r = session.get(f"{PASSPORT}/x/passport-login/web/qrcode/generate", timeout=15)
    gen = r.json()
    if gen.get("code") != 0:
        raise RuntimeError(f"生成登录二维码失败：{gen.get('message')} (code={gen.get('code')})")
    qr_url = gen["data"]["url"]
    qrcode_key = gen["data"]["qrcode_key"]

    info("请用 B 站 App 扫描二维码并确认登录（3 分钟内有效）：")
    if render_qr is not None:
        render_qr(qr_url)
    else:
        _print_qr(qr_url)

    deadline = time.time() + poll_timeout
    status_map = {86101: "等待扫码…", 86090: "已扫码，请在手机上确认…"}
    last_state = None
    while time.time() < deadline:
        if should_cancel is not None and should_cancel():
            raise RuntimeError("登录已取消")
        pr = session.get(
            f"{PASSPORT}/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
            timeout=15,
        ).json()
        code = pr.get("data", {}).get("code")
        if code == 0:
            # 登录成功：cookie 既在响应头里，也在 data.url 的 query 里，两处都收
            cookies = {c.name: c.value for c in session.cookies}
            raw_url = pr["data"].get("url", "")
            for k, v in parse_qs(urlsplit(raw_url).query).items():
                if k in COOKIE_KEYS and v:
                    cookies[k] = v[0]
            cookies = {k: v for k, v in cookies.items() if k in COOKIE_KEYS and v}
            if "SESSDATA" not in cookies:
                raise RuntimeError("登录成功但未取到 SESSDATA cookie，请重试")
            success(f"登录成功，欢迎 UID {cookies.get('DedeUserID', '?')}")
            return cookies
        if code in status_map:
            if code != last_state:
                msg = status_map[code]
                if on_status is not None:
                    on_status(msg)
                else:
                    info(msg)
                last_state = code
        elif code == 86038:
            raise RuntimeError("二维码已过期，请重新打开登录窗口")
        time.sleep(2)
    raise RuntimeError("扫码超时，请重新打开登录窗口")


def save_cookies(path: Path, cookies: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"saved_at": int(time.time()), "cookies": cookies}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cookies(path: Path) -> dict | None:
    """返回 cookie dict；文件不存在或已明显过期返回 None。"""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies") or {}
    except Exception:
        error("cookie 文件损坏，将重新登录")
        return None
    if not cookies.get("SESSDATA"):
        return None
    # SESSDATA 通常有效期约 1 个月，超期直接要求重登（避免反复踩风控）
    if time.time() - payload.get("saved_at", 0) > 45 * 86400:
        warn("cookie 已超过 45 天，建议重新登录")
    return cookies
