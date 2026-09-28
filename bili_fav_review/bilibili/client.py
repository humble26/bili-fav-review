"""B 站 Web API 客户端：收藏夹 / 视频信息 / 字幕，统一限速与错误处理。

仅以个人学习为目的、低频调用；接口行为参考社区维护的 bilibili-API-collect 文档。
"""

import json
import time
from pathlib import Path

import requests

from ..ui import warn
from .wbi import sign_params

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}


class BiliApiError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"B站接口错误 code={code}: {message}")


class NotLoggedInError(BiliApiError):
    def __init__(self, message: str = "未登录或登录已过期"):
        super().__init__(-101, message)


def _ts(seconds: int) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


class BilibiliClient:
    def __init__(self, cookies: dict, interval: float = 1.0, wbi_cache: Path | None = None):
        self.sess = requests.Session()
        self.sess.headers.update(HEADERS)
        for k, v in cookies.items():
            self.sess.cookies.set(k, v, domain=".bilibili.com")
        self.interval = max(0.3, float(interval))
        self._last_request = 0.0
        self._wbi_cache_file = wbi_cache
        self._wbi = self._load_wbi_cache()

    # ---------- 底层 ----------

    def _throttle(self) -> None:
        wait = self.interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _get_json(self, url: str, params: dict | None = None, referer: str | None = None) -> dict:
        headers = {"Referer": referer} if referer else None
        last_exc: Exception | None = None
        for attempt in range(3):
            self._throttle()
            try:
                r = self.sess.get(url, params=params, timeout=20, headers=headers)
                j = r.json()
            except (requests.RequestException, ValueError) as e:
                last_exc = e
                time.sleep(3 * (attempt + 1))
                continue
            code = j.get("code", -1)
            if code == 0:
                return j.get("data") or {}
            if code in (-412, -352):  # 风控拦截：退避重试
                warn(f"触发风控(code={code})，退避 {5 * (attempt + 1)}s 后重试…")
                time.sleep(5 * (attempt + 1))
                continue
            if code == -101:
                raise NotLoggedInError(j.get("message") or "账号登录已失效，请重新运行 login")
            raise BiliApiError(code, j.get("message") or "未知错误")
        if last_exc:
            raise BiliApiError(-1, f"网络错误: {last_exc}")
        raise BiliApiError(-412, "多次触发风控，请稍后再试或调大 sync.request_interval")

    # ---------- WBI ----------

    def _load_wbi_cache(self) -> tuple[str, str] | None:
        if not self._wbi_cache_file or not self._wbi_cache_file.exists():
            return None
        try:
            payload = json.loads(self._wbi_cache_file.read_text(encoding="utf-8"))
            if time.time() - payload.get("ts", 0) < 6 * 3600:
                return payload["img_key"], payload["sub_key"]
        except Exception:
            pass
        return None

    def _save_wbi_cache(self, img_key: str, sub_key: str) -> None:
        if not self._wbi_cache_file:
            return
        try:
            self._wbi_cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._wbi_cache_file.write_text(
                json.dumps({"ts": time.time(), "img_key": img_key, "sub_key": sub_key}),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _get_raw(self, url: str, params: dict | None = None) -> dict:
        """不检查 code 的原始 JSON 请求（nav 匿名访问会返回 code=-101 但携带 wbi key）。"""
        self._throttle()
        r = self.sess.get(url, params=params, timeout=20)
        return r.json()

    def _wbi_keys(self) -> tuple[str, str]:
        if self._wbi:
            return self._wbi
        j = self._get_raw("https://api.bilibili.com/x/web-interface/nav")
        wbi_img = ((j.get("data") or {}).get("wbi_img")) or {}
        img_url, sub_url = wbi_img.get("img_url", ""), wbi_img.get("sub_url", "")
        if not img_url or not sub_url:
            raise BiliApiError(
                j.get("code", -1), f"获取 wbi key 失败: {j.get('message') or '响应中无 wbi_img'}"
            )
        # key 即文件名（不含扩展名）
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        self._wbi = (img_key, sub_key)
        self._save_wbi_cache(img_key, sub_key)
        return self._wbi

    def _get_wbi(self, url: str, params: dict) -> dict:
        img_key, sub_key = self._wbi_keys()
        return self._get_json(url, sign_params(params, img_key, sub_key))

    # ---------- 业务接口 ----------

    def me(self) -> dict:
        """当前登录用户信息；未登录抛 NotLoggedInError。"""
        data = self._get_json("https://api.bilibili.com/x/web-interface/nav")
        if not data.get("isLogin"):
            raise NotLoggedInError()
        return data

    def list_folders(self, mid: int) -> list[dict]:
        data = self._get_json(
            "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
            params={"up_mid": mid},
        )
        # 兼容两种返回形态：纯数组 或 {count, list: [...]} 包装
        if isinstance(data, dict):
            data = data.get("list") or []
        return [f for f in (data or []) if isinstance(f, dict) and f.get("id") is not None]

    def iter_folder_videos(self, media_id: int, page_size: int = 20):
        """遍历收藏夹中的视频（type=2），逐页 yield。"""
        pn = 1
        while True:
            data = self._get_json(
                "https://api.bilibili.com/x/v3/fav/resource/list",
                params={
                    "media_id": media_id,
                    "pn": pn,
                    "ps": page_size,
                    "keyword": "",
                    "order": "mtime",
                    "type": 2,
                    "tid": 0,
                    "platform": "web",
                },
            )
            medias = data.get("medias") or []
            yield from medias
            if not data.get("has_more") or not medias:
                return
            pn += 1

    def get_view(self, bvid: str) -> dict:
        return self._get_json(
            "https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}
        )

    def get_subtitle_list(self, bvid: str, cid: int) -> list[dict]:
        """返回视频的 CC/AI 字幕列表（需 wbi 签名与登录态）。"""
        data = self._get_wbi(
            "https://api.bilibili.com/x/player/wbi/v2", params={"bvid": bvid, "cid": cid}
        )
        return ((data.get("subtitle") or {}).get("subtitles")) or []

    def pick_subtitle(self, subtitles: list[dict], priority: list[str]) -> dict | None:
        """按配置的优先级挑选字幕；优先真实 CC，其次 AI 字幕。"""
        for pref in priority:
            pref_l = str(pref).lower()
            for s in subtitles:
                lan = (s.get("lan") or "").lower()
                if lan == pref_l or lan.startswith(pref_l):
                    return s
        return subtitles[0] if subtitles else None

    def fetch_subtitle_text(self, subtitle_url: str) -> tuple[str, str]:
        """下载字幕 JSON，返回 (语言, 带时间戳的全文)。"""
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url
        elif subtitle_url.startswith("http://"):
            subtitle_url = "https://" + subtitle_url[len("http://"):]
        r = self.sess.get(
            subtitle_url, timeout=20, headers={"Referer": "https://www.bilibili.com/"}
        )
        r.raise_for_status()
        payload = r.json()
        lan = payload.get("lan") or ""
        lines = [
            f"[{_ts(seg.get('from', 0))}] {seg.get('content', '').strip()}"
            for seg in payload.get("body") or []
            if seg.get("content", "").strip()
        ]
        return lan, "\n".join(lines)
