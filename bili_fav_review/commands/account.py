"""账号与提醒：login（扫码登录）/ folders（列出收藏夹）/ due（到期查询+通知）。"""

from datetime import date

from .. import ui
from ..bilibili import BilibiliClient, NotLoggedInError, load_cookies, qr_login, save_cookies
from ..config import load_config
from ..notify import notify
from ..paths import cookies_path, db_path, resolve_data_dir
from ..store import Store


def run_login(args) -> int:
    cfg, _ = load_config(args.config)
    cookies = qr_login()
    path = cookies_path(cfg)
    save_cookies(path, cookies)
    ui.success(f"登录态已保存到 {path}")
    ui.warn("cookie 等同于账号凭证，请勿分享该文件或截图其内容")
    return 0


def run_folders(args) -> int:
    cfg, _ = load_config(args.config)
    cookies = load_cookies(cookies_path(cfg))
    if not cookies:
        ui.error("尚未登录。请先运行: python -m bili_fav_review login")
        return 1
    client = BilibiliClient(
        cookies, interval=1.0, wbi_cache=resolve_data_dir(cfg) / "wbi_cache.json"
    )
    try:
        me = client.me()
    except NotLoggedInError as e:
        ui.error(str(e))
        return 1
    folders = client.list_folders(me["mid"])
    if not folders:
        ui.warn("该账号还没有创建收藏夹")
        return 0
    ui.data_table(
        ["ID", "标题", "视频数"],
        [[f["id"], f["title"], f["media_count"]] for f in folders],
        title=f"{me.get('uname')} 的收藏夹",
    )
    return 0


def run_due(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        n = store.due_count(date.today().isoformat())
        nxt = store.next_due_date()
        ui.info(f"到期卡片: {n}" + (f"（下次到期: {nxt}）" if nxt and not n else ""))
        if n and getattr(args, "notify", False):
            if notify("收藏夹遗忘曲线", f"今天有 {n} 张卡片到期，快去复习吧"):
                ui.info("已发送系统通知")
            else:
                ui.warn("发送系统通知失败（可选依赖: pip install win11toast）")
        if n and getattr(args, "notify", False):
            # 仅在提醒模式下推送，避免手动查询 due 时重复消耗 Server酱额度
            _serverchan_push(cfg, n)
        return 0
    finally:
        store.close()


def _serverchan_push(cfg: dict, n: int) -> None:
    """可选：通过 Server酱 把到期数量推送到微信。"""
    key = (cfg.get("notify") or {}).get("serverchan_sendkey") or ""
    if not key:
        return
    try:
        import requests

        r = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={
                "title": f"📚 收藏夹复习：{n} 张卡片到期",
                "desp": "打开「收藏夹遗忘曲线」开始今天的复习吧。",
            },
            timeout=10,
        )
        ok = r.json().get("code") == 0
        ui.info("Server酱推送: " + ("成功" if ok else f"失败（{r.text[:80]}）"))
    except Exception as e:
        ui.warn(f"Server酱推送失败: {e}")
