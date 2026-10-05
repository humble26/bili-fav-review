# -*- coding: utf-8 -*-
"""由两张 1024px 源图生成多尺寸 app.ico（16/24/32 用加粗变体，48+ 用主设计）。

源图：app-icon-1024.png（主设计）、app-icon-small-1024.png（小尺寸变体）
产物：bili_fav_review/webui/static/app.ico（供窗口图标 / PyInstaller --icon 使用）

重新生成流程：
  1. 修改 app-icon.svg / app-icon-small.svg（设计源）
  2. 用 Edge 无头渲染成上面两张 1024 png（见 重构说明-P2.md「图标重建」一节）
  3. 运行本脚本
"""
import io
import os
import struct

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MASTER = Image.open(os.path.join(HERE, "app-icon-1024.png")).convert("RGBA")
SMALL = Image.open(os.path.join(HERE, "app-icon-small-1024.png")).convert("RGBA")

# (尺寸, 用哪个源) —— 小尺寸用加粗变体保证 16px 下红点仍可辨
SPEC = [(16, "s"), (24, "s"), (32, "s"), (48, "m"), (64, "m"), (128, "m"), (256, "m")]

frames = []
for size, src in SPEC:
    im = (SMALL if src == "s" else MASTER).resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    frames.append((size, buf.getvalue()))

# 手工写 ICO（Vista+ 全部 PNG 帧，Windows 10/11 全尺寸支持）
n = len(frames)
header = struct.pack("<HHH", 0, 1, n)
entries = b""
blobs = b""
offset = 6 + 16 * n
for size, data in frames:
    w = 0 if size == 256 else size  # ICO 中 256 记作 0
    entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
    blobs += data
    offset += len(data)

out = os.path.join(ROOT, "bili_fav_review", "webui", "static", "app.ico")
with open(out, "wb") as f:
    f.write(header + entries + blobs)
print("wrote", out, os.path.getsize(out), "bytes; sizes =", [s for s, _ in frames])
