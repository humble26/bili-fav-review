"""PyInstaller 打包入口（仅打包用；源码运行请直接用 python -m bili_fav_review）。

为什么需要这个文件：PyInstaller 把入口脚本当作顶层 __main__ 执行，
包内 __main__.py 的相对导入（from .cli import main）在冻结环境会失败，
所以这里用绝对导入。行为与 python -m bili_fav_review 完全一致：
无参数 → 图形界面；带子命令 → 对应 CLI 功能（计划任务用的 due --notify 也走这里）。
"""

import sys

from bili_fav_review.cli import main

if __name__ == "__main__":
    sys.exit(main())
