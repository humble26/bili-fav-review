"""WBI 签名（B 站 web 接口风控参数）。

算法来自社区整理的 bilibili-API-collect 文档：
wts = 当前秒级时间戳；参数按 key 排序、过滤 !'()* 字符后拼接，
md5(query + mixin_key) 即 w_rid。
"""

import hashlib
import time
from urllib.parse import urlencode

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

FILTER_CHARS = "!'()*"


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_params(params: dict, img_key: str, sub_key: str, now: int | None = None) -> dict:
    """返回附加了 wts 与 w_rid 的新参数 dict。"""
    mixin_key = get_mixin_key(img_key + sub_key)
    signed = dict(params)
    signed["wts"] = int(now if now is not None else time.time())
    signed = {
        k: "".join(c for c in str(v) if c not in FILTER_CHARS)
        for k, v in sorted(signed.items())
    }
    query = urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return signed
