"""收藏夹遗忘曲线 · B站版 —— 图形界面（tkinter）。

启动方式任选：
  bili-review gui
  python -m bili_fav_review gui
  桌面/开始菜单「收藏夹遗忘曲线」快捷方式（安装器创建，用 pythonw 无黑窗口启动）

设计语言参考「桌面工作台」：左侧深石墨导航栏 + 浅色页面 + 白卡片细边框 +
柔和模块色点缀（绿/蓝/琥珀/紫）+ 深色主按钮。

架构要点：所有网络/同步操作放在后台线程，通过队列把日志与结果送回主线程刷新；
主线程只做本地数据库读写（复习、搜索、统计），保证界面不卡顿。
"""

import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from . import __version__, paths, ui
from . import config as config_mod
from .bilibili import BilibiliClient, load_cookies, qr_login, save_cookies
from .commands.review import _load_card
from .paths import cookies_path, db_path, resolve_data_dir
from .store import (
    GRADE_FORGOT,
    GRADE_FUZZY,
    GRADE_OK,
    Store,
    apply_review,
    make_snippet,
    new_state,
)

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    import tkinter.font as tkfont

    _TK_OK = True
except Exception:  # pragma: no cover
    tk = None
    _TK_OK = False

TASK_NAME = "BiliFavReview"

# ---------------------------------------------------------------- 设计令牌
# 参考「桌面工作台」设计系统：暖中性 · 深石墨
FONT = "Microsoft YaHei UI"
C_PAGE = "#f6f7f9"          # 页面底色
C_CARD = "#ffffff"          # 卡片
C_BORDER = "#e8eaee"        # 卡片细边框
C_BORDER_IN = "#d6d9e0"     # 输入框边框
C_TEXT = "#1b1e26"          # 主文本
C_TEXT2 = "#6b7280"         # 次要文本
C_TEXT3 = "#9aa1ac"         # 三级文本
C_ACCENT = "#262a33"        # 主按钮（深石墨）
C_ACCENT_HOVER = "#383e4c"
C_SIDEBAR = "#1d1f27"       # 侧栏底色
C_SIDEBAR_TOP = "#23252f"
C_NAV_FG = "#b9bec9"        # 侧栏未选中文字
C_NAV_HOVER = "#262833"
C_NAV_ACTIVE = "#343847"    # 侧栏选中底色
C_OK = "#6f8f6a"            # 模块绿（记得）
C_OK_HOVER = "#5d7b58"
C_WARN = "#bd8a4e"          # 模块琥珀（模糊）
C_WARN_HOVER = "#a8793f"
C_DANGER = "#c06051"        # 模块红（忘了）
C_DANGER_HOVER = "#a94f41"
C_INFO = "#5f7a99"          # 模块蓝
C_PURPLE = "#7d7195"        # 模块紫
C_TAG_OK_BG = "#eaf1e8"
C_TAG_MUTED_BG = "#f3f4f7"

LOG_COLORS = {
    "info": "#3a3f4a",
    "success": "#4a7a44",
    "warn": "#a8793f",
    "error": "#b05243",
    "rule": "#9aa1ac",
}

# 界面字体择优链：把 TTF/OTF 丢进 ~/.bili_fav_review/fonts/ 可无限自定义（进程内加载，不装系统）
FONT_CANDIDATES = [
    "HarmonyOS Sans SC", "MiSans", "MiSans Normal",
    "Source Han Sans SC", "思源黑体 CN", "思源黑体",
    "Noto Sans SC", "Noto Sans CJK SC",
    "DengXian", "等线",
    "Microsoft YaHei UI", "Microsoft YaHei",
]

FR_PRIVATE = 0x10


def _load_private_fonts() -> list[str]:
    """进程内加载 ~/.bili_fav_review/fonts/ 下的字体文件，不写入系统、不需要管理员。"""
    folder = paths.default_data_dir() / "fonts"
    if not folder.exists():
        return []
    loaded = []
    try:
        import ctypes

        gdi = ctypes.windll.gdi32
        files = sorted(folder.glob("*.ttf")) + sorted(folder.glob("*.otf")) + sorted(folder.glob("*.ttc"))
        for f in files:
            if gdi.AddFontResourceExW(str(f), FR_PRIVATE, 0):
                loaded.append(f.name)
    except Exception:
        pass
    return loaded


def _pick_font(root) -> str:
    names = set(tkfont.families(root=root))
    for cand in FONT_CANDIDATES:
        if cand in names:
            return cand
    return "Microsoft YaHei UI"

# 界面主队列引用（线程异常钩子用）；App 初始化时赋值
_GUI_QUEUE: "queue.Queue | None" = None


def _append_error_file(text: str) -> None:
    """把异常堆栈追加到 ~/.bili_fav_review/gui_error.log（pythonw 下唯一可靠的报错出口）。"""
    try:
        log = paths.resolve_data_dir({}) / "gui_error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
    except Exception:
        pass


def _thread_excepthook(args):
    """后台线程未捕获异常：写文件 + 尽量送到界面日志，绝不静默消失。"""
    import traceback

    err = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    _append_error_file(err)
    if _GUI_QUEUE is not None:
        try:
            _GUI_QUEUE.put(("log", "error", f"后台线程异常: {args.exc_value}（详情见 gui_error.log）"))
        except Exception:
            pass


HELP_TEXT = """【收藏夹遗忘曲线 · 使用指南（速览版）】

◆ 第一次使用，四步走
  ① 设置页：填 API Key（智谱开放平台 open.bigmodel.cn 免费申请，
     接口填 https://open.bigmodel.cn/api/paas/v4 ，模型 glm-4-flash；
     也可用 DeepSeek 等任何 OpenAI 兼容接口）→ 点「保存配置」
  ② 右上角「扫码登录」：手机 B 站 App 扫二维码并确认
  ③ 登录成功后会自动拉取收藏夹：在列表第一列点 ✓ 勾选要复习的夹子
     → 点「开始同步选中的收藏夹」（会拉字幕、生成复习卡片，视频多时请耐心等）
  ④ 以后每天双击桌面图标 → 首页点「开始复习」

◆ 复习怎么评
  新卡片会直接展示内容（首次学习），通读后评估自己能记多久；
  复习卡先看标题回忆，再点「显示答案」对照，然后诚实点一个：
  😄 记得 → 隔更久再见（2天起步，之后越拉越长）
  🤔 模糊 → 隔 1~2 天再来
  😅 忘了 → 明天就再见
  评分越诚实，安排越准；这是给自己复习，不用客气也不用逞强。

◆ 常见问题
  · 点了没反应？看底部「运行日志」；再不行打开数据文件夹里的
    gui.log / gui_error.log 发给作者
  · 登录失效（约 45 天）？重新扫码即可
  · 有的卡片缺摘要？点「卡片库 → 🤖 补齐缺失摘要」，无字幕视频
    会用标题+简介批量轻摘（省成本），之后同步会自动升级为字幕精摘
  · 同步很慢/卡住？每次限量处理，多跑几次即可增量补完
  · 想换收藏夹？在「我的收藏夹」页重新勾选再同步

◆ 数据与隐私
  所有数据（数据库/cookie/配置）都在本机 ~/.bili_fav_review/，
  发给 AI 的只有视频标题、简介与字幕文本。完整版指南见安装目录《使用指南.md》。
"""

GUIDE_STEPS = (
    "① 「设置」页填入 AI 的 API Key（智谱 GLM 有免费额度，或 DeepSeek/本地模型）\n"
    "② 点右上角「扫码登录」，用 B 站 App 扫二维码\n"
    "③ 登录后自动拉取收藏夹：勾选要复习的夹子，点「开始同步」\n"
    "④ 之后每天打开本程序，首页点「开始复习」即可"
)


def _client(cfg: dict) -> BilibiliClient:
    """用已存 cookie 建客户端（各后台线程各自建，避免跨线程共享 session）。"""
    interval = (cfg.get("sync") or {}).get("request_interval", 1.0)
    return BilibiliClient(
        load_cookies(cookies_path(cfg)) or {},
        interval=max(0.6, float(interval)),
        wbi_cache=resolve_data_dir(cfg) / "wbi_cache.json",
    )


class App:
    # 侧栏导航定义：(key, 图标, 名称, 页面标题)
    VIEWS = [
        ("home", "🏠", "首页", "首页"),
        ("folders", "📂", "我的收藏夹", "我的收藏夹"),
        ("review", "🧠", "复习", "今日复习"),
        ("cards", "🗂", "卡片库", "卡片库"),
        ("search", "🔍", "搜索", "搜索收藏"),
        ("stats", "📊", "统计", "学习统计"),
        ("settings", "⚙", "设置", "设置"),
    ]

    def __init__(self):
        global _GUI_QUEUE
        self.root = tk.Tk()
        self.root.title(f"收藏夹遗忘曲线 · B站版 v{__version__}")
        self.root.geometry("980x700")
        self.root.minsize(860, 620)
        self.root.configure(bg=C_PAGE)

        self.q: queue.Queue = queue.Queue()
        _GUI_QUEUE = self.q
        ui.set_sink(lambda level, text: self.q.put(("log", level, text)))
        # tkinter 回调异常也绝不静默：写文件 + 界面日志
        self.root.report_callback_exception = self._tk_callback_exception

        self.cfg, _ = config_mod.load_config()
        self.cfg_path = config_mod.resolve_config_path()
        self.store = Store(db_path(self.cfg))

        self.logged_in = False
        self._sel_folder_ids: set[int] = set()
        self._login_cancel = False
        self._login_win = None
        self._sync_busy = False
        self._fill_busy = False
        self._anki_busy = False
        self._review_cards = []
        self._review_idx = 0
        self._revealed = False
        self._active_view = "home"
        self._stat_vars = None
        self._home_btn_text = tk.StringVar(value="▶  开始复习")
        self._font_note = ""
        self._undo_snapshot = None
        self._chart_data = None

        self._build_ui()
        self.root.bind("<Key>", self._review_key)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_queue)
        self.root.after(250, self.refresh_all)

    # ---------------------------------------------------------------- 样式与骨架

    def _setup_styles(self):
        global FONT
        private = _load_private_fonts()
        FONT = _pick_font(self.root)
        self._font_note = "界面字体: " + FONT + (
            f"（私有字体: {', '.join(private)}）" if private
            else "（想换字体？把 TTF 丢进数据目录的 fonts 文件夹即可）"
        )
        style = ttk.Style()
        try:
            style.theme_use("clam")  # clam 允许完全自定义配色
        except Exception:
            pass
        style.configure(".", background=C_PAGE, foreground=C_TEXT, borderwidth=0,
                        font=(FONT, 11))
        style.configure("TFrame", background=C_PAGE)
        style.configure("TLabel", background=C_PAGE, foreground=C_TEXT)
        style.configure("Card.TFrame", background=C_CARD)
        style.configure("Card.TLabel", background=C_CARD, foreground=C_TEXT)
        style.configure("Muted.TLabel", background=C_PAGE, foreground=C_TEXT2)
        style.configure("CardMuted.TLabel", background=C_CARD, foreground=C_TEXT2)
        # 卡片容器
        style.configure("Card.TLabelframe", background=C_CARD, bordercolor=C_BORDER,
                        relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=C_CARD, foreground=C_TEXT,
                        font=(FONT, 10, "bold"))
        # 按钮
        style.configure("TButton", background=C_CARD, foreground=C_TEXT,
                        bordercolor=C_BORDER_IN, focuscolor=C_ACCENT,
                        padding=(13, 7), relief="flat")
        style.map("TButton",
                  background=[("active", "#eef0f4"), ("disabled", C_TAG_MUTED_BG)],
                  foreground=[("disabled", C_TEXT3)])
        style.configure("Accent.TButton", background=C_ACCENT, foreground="#ffffff",
                        padding=(14, 7))
        style.map("Accent.TButton",
                  background=[("active", C_ACCENT_HOVER), ("disabled", "#565b66")],
                  foreground=[("disabled", "#d8dae0")])
        for name, base, hover in (
            ("Ok.TButton", C_OK, C_OK_HOVER),
            ("Warn.TButton", C_WARN, C_WARN_HOVER),
            ("Danger.TButton", C_DANGER, C_DANGER_HOVER),
        ):
            style.configure(name, background=base, foreground="#ffffff", padding=(12, 6))
            style.map(name,
                      background=[("disabled", "#d9dce1"), ("active", hover)],
                      foreground=[("disabled", "#eef0f2")])
        # 输入
        style.configure("TEntry", fieldbackground=C_CARD, background=C_CARD,
                        bordercolor=C_BORDER_IN, lightcolor=C_BORDER_IN,
                        darkcolor=C_BORDER_IN, padding=4)
        style.configure("TCombobox", fieldbackground=C_CARD, background=C_CARD,
                        bordercolor=C_BORDER_IN, arrowcolor=C_TEXT2, padding=3)
        style.map("TCombobox", fieldbackground=[("readonly", C_CARD)],
                  bordercolor=[("focus", C_INFO)])
        style.configure("TCheckbutton", background=C_PAGE, foreground=C_TEXT,
                        focuscolor=C_PAGE)
        style.map("TCheckbutton", background=[("active", C_PAGE)])
        # 表格
        style.configure("Treeview", background=C_CARD, fieldbackground=C_CARD,
                        foreground=C_TEXT, rowheight=33, bordercolor=C_BORDER,
                        font=(FONT, 11))
        style.configure("Treeview.Heading", background="#f3f4f7", foreground=C_TEXT2,
                        font=(FONT, 10, "bold"), relief="flat", padding=(8, 6))
        style.map("Treeview",
                  background=[("selected", "#eceef2")],
                  foreground=[("selected", C_TEXT)])
        try:
            tkfont.nametofont("TkDefaultFont").configure(family=FONT, size=11)
        except Exception:
            pass

    def _build_ui(self):
        self._setup_styles()

        # ---- 左侧深石墨导航栏 ----
        side = tk.Frame(self.root, bg=C_SIDEBAR, width=212)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._build_sidebar(side)

        # ---- 右侧主列 ----
        main = tk.Frame(self.root, bg=C_PAGE)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        header.pack(fill="x")
        self._build_header(header)

        body = tk.Frame(main, bg=C_PAGE)
        body.pack(fill="both", expand=True)

        # 页面栈（place 叠放，show_view 负责切换）
        self.page_root = tk.Frame(body, bg=C_PAGE)
        self.page_root.pack(fill="both", expand=True)
        self._pages = {}
        self._build_page_home(self._page("home"))
        self._build_page_folders(self._page("folders"))
        self._build_page_review(self._page("review"))
        self._build_page_cards(self._page("cards"))
        self._build_page_search(self._page("search"))
        self._build_page_stats(self._page("stats"))
        self._build_page_settings(self._page("settings"))

        self._build_log_panel(body)
        if self._font_note:
            self._append_log("info", self._font_note)

    def _page(self, key: str):
        f = tk.Frame(self.page_root, bg=C_PAGE)
        self._pages[key] = f
        f.place(relx=0, rely=0, relwidth=1, relheight=1)
        return f

    def _build_sidebar(self, side):
        brand = tk.Frame(side, bg=C_SIDEBAR)
        brand.pack(fill="x", padx=14, pady=(18, 16))
        logo = tk.Label(brand, text="📚", bg="#76809f", fg="white",
                        font=(FONT, 16), width=3, height=1)
        logo.pack(side="left")
        bt = tk.Frame(brand, bg=C_SIDEBAR)
        bt.pack(side="left", padx=(10, 0))
        tk.Label(bt, text="收藏夹遗忘曲线", font=(FONT, 12, "bold"),
                 bg=C_SIDEBAR, fg="#f4f5f8").pack(anchor="w")
        tk.Label(bt, text="BILIBILI REVIEW", font=(FONT, 8, "bold"),
                 bg=C_SIDEBAR, fg="#7d828f").pack(anchor="w")

        tk.Frame(side, bg="#2a2c37", height=1).pack(fill="x", padx=12)

        self._nav_items = {}
        for key, icon, label, _title in self.VIEWS:
            lbl = tk.Label(
                side, text=f"  {icon}   {label}", anchor="w",
                bg=C_SIDEBAR, fg=C_NAV_FG, font=(FONT, 11),
                padx=12, pady=8, cursor="hand2",
            )
            lbl.pack(fill="x", padx=10, pady=1)
            lbl.bind("<Button-1>", lambda e, k=key: self.show_view(k))
            lbl.bind("<Enter>", lambda e, l=lbl: l.cget("bg") != C_NAV_ACTIVE and l.config(bg=C_NAV_HOVER))
            lbl.bind("<Leave>", lambda e, l=lbl: l.cget("bg") != C_NAV_ACTIVE and l.config(bg=C_SIDEBAR))
            self._nav_items[key] = lbl

        foot = tk.Frame(side, bg=C_SIDEBAR)
        foot.pack(side="bottom", fill="x", padx=14, pady=10)
        tk.Frame(foot, bg="#2a2c37", height=1).pack(fill="x", pady=(0, 8))
        tk.Label(foot, text=f"v{__version__}", font=(FONT, 9),
                 bg=C_SIDEBAR, fg="#6f7480").pack(side="left")
        tk.Label(foot, text="本地优先 · 隐私安全", font=(FONT, 9),
                 bg=C_SIDEBAR, fg="#6f7480").pack(side="right")

    def _build_header(self, header):
        self.var_login_state = tk.StringVar(value="○ 检查登录状态…")
        left = tk.Frame(header, bg=C_CARD)
        left.pack(side="left", padx=22, pady=10)
        self.var_page_title = tk.StringVar(value="首页")
        tk.Label(left, textvariable=self.var_page_title, font=(FONT, 16, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(side="left")
        self._login_chip = tk.Label(left, textvariable=self.var_login_state,
                                    font=(FONT, 10), bg=C_TAG_MUTED_BG, fg=C_TEXT2, padx=10, pady=4)
        self._login_chip.pack(side="left", padx=(14, 0))

        right = tk.Frame(header, bg=C_CARD)
        right.pack(side="right", padx=16, pady=8)
        ttk.Button(right, text="扫码登录", style="Accent.TButton",
                   command=self.open_login).pack(side="right")
        ttk.Button(right, text="使用指南", command=self.open_help).pack(side="right", padx=6)
        ttk.Button(right, text="刷新", command=self.refresh_all).pack(side="right")

    def show_view(self, key: str):
        self._active_view = key
        self._pages[key].lift()
        title = dict((v[0], v[3]) for v in self.VIEWS).get(key, key)
        self.var_page_title.set(title)
        for k, lbl in self._nav_items.items():
            active = k == key
            lbl.config(
                bg=C_NAV_ACTIVE if active else C_SIDEBAR,
                fg="#ffffff" if active else C_NAV_FG,
                font=(FONT, 11, "bold") if active else (FONT, 11),
            )
        if key == "cards":
            self.refresh_cards()
        elif key == "stats":
            self.refresh_stats()
        elif key == "home":
            self._refresh_home()

    def _build_log_panel(self, parent):
        wrap = tk.Frame(parent, bg=C_PAGE)
        wrap.pack(fill="x", padx=26, pady=(4, 14))
        head = tk.Frame(wrap, bg=C_PAGE)
        head.pack(fill="x")
        tk.Label(head, text="运行日志", font=(FONT, 10, "bold"),
                 bg=C_PAGE, fg=C_TEXT3).pack(side="left")
        ttk.Button(head, text="清空", width=6, command=self._clear_log).pack(side="right")
        self.txt_log = tk.Text(
            wrap, height=6, wrap="word", relief="flat",
            background=C_CARD, foreground="#3a3f4a",
            highlightthickness=1, highlightbackground=C_BORDER,
            padx=12, pady=8, font=(FONT, 10), state="disabled",
        )
        self.txt_log.pack(fill="x", pady=(4, 0))
        for tag, color in LOG_COLORS.items():
            self.txt_log.tag_configure(tag, foreground=color)

    # ---------------------------------------------------------------- 队列与日志

    def _poll_queue(self):
        """队列轮询：任何一条消息的处理异常都不能杀死轮询本身（否则界面永久失聪）。"""
        try:
            for _ in range(200):
                kind, a, b = self.q.get_nowait()
                try:
                    handler = getattr(self, f"_on_{kind}", None)
                    if handler:
                        handler(a, b)
                    else:
                        self._append_log("info", f"{kind}: {a}")
                except Exception as e:
                    import traceback

                    _append_error_file(traceback.format_exc())
                    self._append_log("error", f"处理 {kind} 时出错: {e}（详情见 gui_error.log）")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_queue)

    def _tk_callback_exception(self, exc, val, tb):
        import traceback

        _append_error_file("".join(traceback.format_exception(exc, val, tb)))
        try:
            self._append_log("error", f"界面异常: {val}（详情见 gui_error.log）")
        except Exception:
            pass

    def _append_log(self, level: str, text: str):
        try:  # 镜像到文件，pythonw 下排查问题全靠它
            log = resolve_data_dir(self.cfg) / "gui.log"
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {text}\n")
        except Exception:
            pass
        self.txt_log.config(state="normal")
        if level == "rule":
            self.txt_log.insert("end", f"\n────── {text} ──────\n", "rule")
        else:
            self.txt_log.insert("end", text + "\n", level)
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")

    def _on_log(self, level, text):
        self._append_log(level, text)

    # ---------------------------------------------------------------- 页面构建

    def _build_page_home(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 4))

        # —— 今日复习 hero 卡 ——
        hero = tk.Frame(wrap, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        hero.pack(fill="x")
        tk.Frame(hero, bg=C_INFO, width=4).pack(side="left", fill="y")
        inner = tk.Frame(hero, bg=C_CARD)
        inner.pack(fill="x", padx=22, pady=16)
        left = tk.Frame(inner, bg=C_CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="今天该复习了", font=(FONT, 18, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(anchor="w")
        self.var_home_due = tk.StringVar(value="统计中…")
        tk.Label(left, textvariable=self.var_home_due, font=(FONT, 11),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor="w", pady=(5, 0))
        tk.Button(
            inner, textvariable=self._home_btn_text, command=self.start_review,
            font=(FONT, 13, "bold"), bg=C_ACCENT, fg="#ffffff",
            activebackground=C_ACCENT_HOVER, activeforeground="#ffffff",
            relief="flat", cursor="hand2", padx=28, pady=11, bd=0,
        ).pack(side="right", padx=(14, 0))

        # —— 统计磁贴 ——
        row = tk.Frame(wrap, bg=C_PAGE)
        row.pack(fill="x", pady=(12, 0))
        self.var_stats = tk.StringVar(value="")  # 兼容保留（调试/冒烟脚本）
        self._stat_vars = {}
        for key, label, color in (
            ("total", "收藏视频", C_INFO),
            ("subtitle", "已有字幕", C_OK),
            ("summary", "已生成卡片", C_WARN),
            ("mature", "长期记忆", C_PURPLE),
        ):
            tile = tk.Frame(row, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
            tile.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tin = tk.Frame(tile, bg=C_CARD)
            tin.pack(fill="x", padx=16, pady=11)
            tk.Label(tin, text="●", font=(FONT, 9), bg=C_CARD, fg=color).pack(anchor="w")
            var = tk.StringVar(value="0")
            self._stat_vars[key] = var
            tk.Label(tin, textvariable=var, font=(FONT, 24, "bold"),
                     bg=C_CARD, fg=C_TEXT).pack(anchor="w")
            tk.Label(tin, text=label, font=(FONT, 10), bg=C_CARD, fg=C_TEXT2).pack(anchor="w")

        # —— 首次使用引导 ——
        guide = ttk.Labelframe(wrap, text=" 第一次使用？照这四步走 ",
                               style="Card.TLabelframe", padding=12)
        guide.pack(fill="x", pady=(12, 0))
        ttk.Label(guide, text=GUIDE_STEPS, style="CardMuted.TLabel",
                  justify="left", wraplength=880).pack(anchor="w")

    def _build_page_folders(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        bar = tk.Frame(wrap, bg=C_PAGE)
        bar.pack(fill="x")
        self.btn_refresh_folders = ttk.Button(
            bar, text="↻ 拉取收藏夹列表", command=self.refresh_folders
        )
        self.btn_refresh_folders.pack(side="left")
        ttk.Button(bar, text="全选", command=self._select_all_folders).pack(side="left", padx=6)
        self.var_sync_llm = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="生成 AI 复习卡片（需要 API Key）",
                        variable=self.var_sync_llm).pack(side="left", padx=(14, 0))
        tk.Label(bar, text="本次最多", font=(FONT, 10), bg=C_PAGE, fg=C_TEXT3).pack(
            side="left", padx=(14, 3))
        self.var_sync_limit = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.var_sync_limit, width=5).pack(side="left")
        tk.Label(bar, text="个", font=(FONT, 10), bg=C_PAGE, fg=C_TEXT3).pack(side="left")
        self._sync_btn = ttk.Button(bar, text="▶  开始同步选中的收藏夹", style="Accent.TButton",
                                    command=self.start_sync, state="disabled")
        self._sync_btn.pack(side="right")

        hint = tk.Frame(wrap, bg=C_PAGE)
        hint.pack(fill="x", pady=(8, 4))
        tk.Label(hint, text="点击表格第一列的 ✓ 勾选/取消 · 同步是增量的，重复执行无副作用 · 失效视频自动跳过",
                 font=(FONT, 10), bg=C_PAGE, fg=C_TEXT3).pack(side="left")

        tree_card = tk.Frame(wrap, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        tree_card.pack(fill="both", expand=True, pady=(0, 0))
        cols = ("sel", "title", "count", "id")
        self.tree_folders = ttk.Treeview(tree_card, columns=cols, show="headings", height=12)
        for cid, text, w, anchor in (
            ("sel", "选中", 50, "center"),
            ("title", "收藏夹", 380, "w"),
            ("count", "视频数", 80, "e"),
            ("id", "ID", 90, "e"),
        ):
            self.tree_folders.heading(cid, text=text)
            self.tree_folders.column(cid, width=w, anchor=anchor)
        self.tree_folders.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree_folders.bind("<Button-1>", self._toggle_folder)

    def _build_page_review(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        top = tk.Frame(wrap, bg=C_PAGE)
        top.pack(fill="x")
        self.var_r_progress = tk.StringVar(value="还没有开始复习")
        tk.Label(top, textvariable=self.var_r_progress, font=(FONT, 11),
                 bg=C_PAGE, fg=C_TEXT2).pack(side="left")
        tk.Label(top, text="快捷键：空格 显示答案 · 1/2/3 评分 · S 跳过",
                 font=(FONT, 9), bg=C_PAGE, fg=C_TEXT3).pack(side="right")

        head = ttk.Labelframe(wrap, text=" 回忆一下 ", style="Card.TLabelframe", padding=12)
        head.pack(fill="x", pady=(8, 0))
        self.var_r_title = tk.StringVar(value="——")
        ttk.Label(head, textvariable=self.var_r_title, style="Card.TLabel",
                  font=(FONT, 14, "bold"), wraplength=840).pack(anchor="w")
        self.var_r_meta = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.var_r_meta, style="CardMuted.TLabel").pack(anchor="w")
        self.var_r_oneliner = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.var_r_oneliner, style="Card.TLabel",
                  wraplength=840).pack(anchor="w", pady=(4, 0))
        self.var_r_quiz = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.var_r_quiz, style="CardMuted.TLabel",
                  foreground=C_INFO, wraplength=840).pack(anchor="w", pady=(4, 0))

        btnrow = tk.Frame(wrap, bg=C_PAGE)
        btnrow.pack(fill="x", pady=(8, 0))
        self.btn_reveal = ttk.Button(btnrow, text="👁 显示答案",
                                     command=self.reveal_answer, state="disabled")
        self.btn_reveal.pack(side="left")
        ttk.Button(btnrow, text="🌐 重看视频", command=self._open_current_video).pack(
            side="left", padx=6)

        ans = ttk.Labelframe(wrap, text=" 答案 ", style="Card.TLabelframe", padding=12)
        ans.pack(fill="both", expand=True, pady=(8, 0))
        self.txt_answer = tk.Text(
            ans, height=9, wrap="word", relief="flat", background=C_CARD,
            foreground=C_TEXT, padx=4, pady=2, bd=0, highlightthickness=0,
            font=(FONT, 11), state="disabled",
        )
        self.txt_answer.pack(fill="both", expand=True)

        grade = tk.Frame(wrap, bg=C_PAGE)
        grade.pack(fill="x", pady=8)
        self.btn_forgot = ttk.Button(grade, text="😅  忘了", style="Danger.TButton",
                                     command=lambda: self._grade(GRADE_FORGOT), state="disabled")
        self.btn_fuzzy = ttk.Button(grade, text="🤔  模糊", style="Warn.TButton",
                                    command=lambda: self._grade(GRADE_FUZZY), state="disabled")
        self.btn_ok = ttk.Button(grade, text="😄  记得", style="Ok.TButton",
                                 command=lambda: self._grade(GRADE_OK), state="disabled")
        for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
            b.pack(side="left", expand=True, fill="x", padx=5, ipady=4)
        self.btn_undo = ttk.Button(grade, text="↩ 撤销", command=self._undo_grade,
                                   state="disabled")
        self.btn_undo.pack(side="right", padx=(6, 0))
        ttk.Button(grade, text="跳过这张", command=self._skip_card).pack(
            side="right", padx=(6, 0))

        self.btn_promote = ttk.Button(f, command=self._promote_and_review)
        self.btn_promote.pack_forget()

    def _build_page_cards(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        bar = tk.Frame(wrap, bg=C_PAGE)
        bar.pack(fill="x")
        ttk.Button(bar, text="↻ 刷新", command=self.refresh_cards).pack(side="left")
        self.btn_fill = ttk.Button(bar, text="🤖 补齐缺失摘要", style="Accent.TButton",
                                   command=self.fill_missing_summaries)
        self.btn_fill.pack(side="left", padx=8)
        self.btn_anki = ttk.Button(bar, text="📤 导出 Anki", command=self.export_anki)
        self.btn_anki.pack(side="left")
        tk.Label(bar, text="筛选", font=(FONT, 10), bg=C_PAGE, fg=C_TEXT3).pack(
            side="left", padx=(14, 3))
        self.var_card_filter = tk.StringVar(value="全部")
        box = ttk.Combobox(bar, textvariable=self.var_card_filter, width=10, state="readonly",
                           values=["全部", "新卡", "今日到期", "已逾期", "长期记忆"])
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.refresh_cards())
        self.var_card_count = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.var_card_count, font=(FONT, 9),
                 bg=C_PAGE, fg=C_TEXT3).pack(side="left", padx=10)
        tk.Label(bar, text="双击查看完整卡片（不影响复习排期）", font=(FONT, 9),
                 bg=C_PAGE, fg=C_TEXT3).pack(side="right")

        tree_card = tk.Frame(wrap, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        tree_card.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("status", "title", "up", "due", "interval")
        self.tree_cards = ttk.Treeview(tree_card, columns=cols, show="headings", height=14)
        for cid, text, w, anchor in (
            ("status", "状态", 92, "center"),
            ("title", "标题", 330, "w"),
            ("up", "UP主", 110, "w"),
            ("due", "到期日", 90, "center"),
            ("interval", "间隔(天)", 70, "e"),
        ):
            self.tree_cards.heading(cid, text=text)
            self.tree_cards.column(cid, width=w, anchor=anchor)
        self.tree_cards.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree_cards.bind("<Double-1>", self._open_card_detail)

    def _build_page_search(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        bar = tk.Frame(wrap, bg=C_PAGE)
        bar.pack(fill="x")
        self.var_search = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.var_search)
        ent.pack(side="left", fill="x", expand=True, ipady=2)
        ent.bind("<Return>", lambda e: self.do_search())
        ttk.Button(bar, text="🔍 搜索收藏", style="Accent.TButton",
                   command=self.do_search).pack(side="left", padx=8)
        tk.Label(bar, text="可搜标题 / 简介 / 字幕 / 摘要卡片", font=(FONT, 9),
                 bg=C_PAGE, fg=C_TEXT3).pack(side="left")

        tree_card = tk.Frame(wrap, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        tree_card.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("title", "up", "folder", "snippet")
        self.tree_search = ttk.Treeview(tree_card, columns=cols, show="headings", height=14)
        for cid, text, w, anchor in (
            ("title", "标题", 300, "w"),
            ("up", "UP主", 120, "w"),
            ("folder", "收藏夹", 120, "w"),
            ("snippet", "命中片段", 300, "w"),
        ):
            self.tree_search.heading(cid, text=text)
            self.tree_search.column(cid, width=w, anchor=anchor)
        self.tree_search.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree_search.bind("<Double-1>", self._open_search_detail)
        tk.Label(wrap, text="双击结果查看完整复习卡片", font=(FONT, 9),
                 bg=C_PAGE, fg=C_TEXT3).pack(anchor="w", pady=(6, 0))

    def _build_page_settings(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 6))

        box = ttk.Labelframe(wrap, text=" AI 摘要设置（OpenAI 兼容接口均可） ",
                             style="Card.TLabelframe", padding=16)
        box.pack(fill="x")
        self.var_set_key = tk.StringVar(value=(self.cfg.get("llm") or {}).get("api_key", ""))
        self.var_set_base = tk.StringVar(value=(self.cfg.get("llm") or {}).get("base_url", ""))
        self.var_set_model = tk.StringVar(value=(self.cfg.get("llm") or {}).get("model", ""))
        for i, (label, attr, secret) in enumerate((
            ("API Key", "var_set_key", True),
            ("接口地址 base_url", "var_set_base", False),
            ("模型 model", "var_set_model", False),
        )):
            ttk.Label(box, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ent = ttk.Entry(box, textvariable=getattr(self, attr), width=56)
            if secret:
                ent.config(show="•")
            ent.grid(row=i, column=1, sticky="we", padx=10, pady=4)
        box.columnconfigure(1, weight=1)
        ttk.Button(box, text="💾 保存配置", style="Accent.TButton",
                   command=self.save_settings).grid(row=3, column=1, sticky="e", pady=6)
        ttk.Label(box, style="CardMuted.TLabel", wraplength=620, justify="left",
                  text="免费推荐：base_url=https://open.bigmodel.cn/api/paas/v4  "
                       "model=glm-4-flash（智谱开放平台申请 Key）；DeepSeek 填 "
                       "https://api.deepseek.com/v1 / deepseek-chat",
                  ).grid(row=4, column=0, columnspan=2, sticky="w")

        task = ttk.Labelframe(wrap, text=" 每日提醒（弹系统通知） ",
                              style="Card.TLabelframe", padding=16)
        task.pack(fill="x", pady=(14, 0))
        ttk.Label(task, text="每天", style="Card.TLabel").pack(side="left")
        self.var_task_time = tk.StringVar(value="09:30")
        ttk.Entry(task, textvariable=self.var_task_time, width=7).pack(side="left", padx=6)
        ttk.Label(task, text="点弹出复习提醒", style="Card.TLabel").pack(side="left")
        ttk.Button(task, text="创建 / 更新提醒", command=self.create_task).pack(side="left", padx=12)
        ttk.Button(task, text="移除提醒", command=self.remove_task).pack(side="left")
        self.var_task_status = tk.StringVar(value="")
        ttk.Label(task, textvariable=self.var_task_status, style="CardMuted.TLabel").pack(
            side="left", padx=10)

        data = ttk.Labelframe(wrap, text=" 数据 ", style="Card.TLabelframe", padding=16)
        data.pack(fill="x", pady=(14, 0))
        self.var_data_dir = tk.StringVar(value=str(resolve_data_dir(self.cfg)))
        ttk.Label(data, textvariable=self.var_data_dir, style="CardMuted.TLabel").pack(side="left")
        ttk.Button(data, text="打开数据文件夹", command=self._open_data_dir).pack(side="right")

        push = ttk.Labelframe(wrap, text=" 微信推送（可选，Server酱） ",
                              style="Card.TLabelframe", padding=16)
        push.pack(fill="x", pady=(14, 0))
        self.var_set_sendkey = tk.StringVar(
            value=(self.cfg.get("notify") or {}).get("serverchan_sendkey", ""))
        ttk.Label(push, text="SendKey", style="Card.TLabel").pack(side="left")
        ttk.Entry(push, textvariable=self.var_set_sendkey, width=46, show="•").pack(
            side="left", padx=10)
        ttk.Button(push, text="💾 保存", command=self.save_push_settings).pack(side="left")
        ttk.Label(push, style="CardMuted.TLabel",
                  text="sct.ftqq.com 免费申请；保存后每日提醒会把到期数量推到微信",
                  wraplength=360, justify="left").pack(side="left", padx=10)

    # ---------------------------------------------------------------- 全局刷新

    def refresh_all(self):
        try:
            if self.store.backup():
                self._append_log("success", "已自动备份数据库（保留最近 7 份）")
        except Exception as e:
            self._append_log("warn", f"自动备份失败（不影响使用）: {e}")
        self._refresh_home()
        threading.Thread(target=self._verify_login_worker, daemon=True).start()
        self._refresh_task_status()

    def _refresh_home(self):
        c = self.store.counts()
        today = date.today().isoformat()
        due_new, due_old = self.store.due_breakdown(today)
        due = due_new + due_old
        if self._stat_vars is not None:
            self._stat_vars["total"].set(str(c["total"]))
            self._stat_vars["subtitle"].set(str(c["with_transcript"]))
            self._stat_vars["summary"].set(str(c["with_summary"]))
            self._stat_vars["mature"].set(str(c["mature"]))
        self.var_stats.set(  # 保留：调试/冒烟脚本使用
            f"收藏视频 {c['total']} · 已有字幕 {c['with_transcript']} · 已生成卡片 {c['with_summary']}"
            f" · 长期记忆 {c['mature']}"
        )
        if due:
            self._home_btn_text.set(f"▶  开始复习（{due} 张）")
            self.var_home_due.set(f"今日到期 {due} 张 —— 🆕 新卡 {due_new} · 复习 {due_old}")
        else:
            nxt = self.store.next_due_date()
            self._home_btn_text.set("▶  今天没有到期卡片")
            self.var_home_due.set(
                "今天没有到期卡片，休息一下 🎉" + (f"    下一批到期：{nxt}" if nxt else "")
            )
        tip = f"下一批到期: {nxt}" if (nxt := self.store.next_due_date()) and not due else ""
        self.var_r_progress.set(tip or self.var_r_progress.get())

    def _verify_login_worker(self):
        cookies = load_cookies(cookies_path(self.cfg))
        if not cookies:
            self.q.put(("login_state", False, "未登录 —— 点右上角「扫码登录」"))
            return
        try:
            me = _client(self.cfg).me()
            self.q.put(("login_state", True, f"已登录 · {me.get('uname')}"))
        except Exception as e:
            self.q.put(("login_state", False, f"登录已失效，请重新扫码（{e}）"))

    def _on_login_state(self, ok, text):
        self.logged_in = bool(ok)
        self.var_login_state.set(("● " if ok else "○ ") + text)
        self._login_chip.config(
            bg=C_TAG_OK_BG if ok else C_TAG_MUTED_BG,
            fg="#4a7a44" if ok else C_TEXT2,
        )
        self._sync_btn.config(state="normal" if self.logged_in else "disabled")

    # ---------------------------------------------------------------- 登录

    def open_login(self):
        if self._login_win is not None and self._login_win.winfo_exists():
            self._login_win.lift()
            return
        self._login_cancel = False
        win = tk.Toplevel(self.root)
        win.title("扫码登录 B 站")
        win.geometry("420x480")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=C_PAGE)
        ttk.Label(
            win, text="打开手机 B 站 App → 扫一扫，扫描下方二维码并确认登录",
            wraplength=380, justify="center", style="Muted.TLabel",
        ).pack(pady=(14, 6))
        canvas = tk.Canvas(win, width=380, height=380, background="white", highlightthickness=1,
                           highlightbackground=C_BORDER, bd=0)
        canvas.pack()
        self._qr_canvas = canvas
        var_status = tk.StringVar(value="正在获取二维码…")
        ttk.Label(win, textvariable=var_status, foreground=C_INFO, style="Muted.TLabel").pack(pady=8)
        self._login_status_var = var_status
        ttk.Button(win, text="取消", command=self._cancel_login).pack(pady=(2, 12))
        self._login_win = win
        win.protocol("WM_DELETE_WINDOW", self._cancel_login)
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _cancel_login(self):
        self._login_cancel = True
        if self._login_win is not None:
            self._login_win.destroy()
            self._login_win = None

    def _login_worker(self):
        try:
            cookies = qr_login(
                render_qr=lambda url: self.q.put(("qr", url, None)),
                on_status=lambda s: self.q.put(("login_status", s, None)),
                should_cancel=lambda: self._login_cancel,
            )
            save_cookies(cookies_path(self.cfg), cookies)
            self.q.put(("login_success", cookies.get("DedeUserID", "?"), None))
        except Exception as e:
            self.q.put(("log", "error", f"登录失败: {e}"))
            self.q.put(("login_failed", str(e), None))

    def _on_qr(self, url, _):
        try:
            import qrcode

            qr = qrcode.QRCode(border=2)
            qr.add_data(url)
            qr.make(fit=True)
            matrix = qr.get_matrix()
        except Exception as e:
            self._append_log("error", f"二维码生成失败: {e}")
            return
        cell = max(2, min(7, 360 // len(matrix)))
        size = len(matrix) * cell
        canvas = self._qr_canvas
        canvas.config(width=size, height=size)
        canvas.delete("all")
        for y, row in enumerate(matrix):
            for x, filled in enumerate(row):
                if filled:
                    canvas.create_rectangle(
                        x * cell, y * cell, (x + 1) * cell, (y + 1) * cell,
                        fill="black", outline="black",
                    )
        self._login_status_var.set("等待扫码…")

    def _on_login_status(self, text, _):
        self._login_status_var.set(text)

    def _on_login_success(self, uid, _):
        if self._login_win is not None:
            self._login_win.destroy()
            self._login_win = None
        messagebox.showinfo("登录成功", f"欢迎，UID {uid}！\n正在为你拉取收藏夹…")
        self.refresh_all()
        # 登录后直接跳到收藏夹页并自动拉取，少点一步
        self.show_view("folders")
        self.refresh_folders()

    def _on_login_failed(self, msg, _):
        if self._login_win is not None and self._login_win.winfo_exists():
            self._login_status_var.set("登录失败，可关闭窗口重试")

    # ---------------------------------------------------------------- 收藏夹与同步

    def refresh_folders(self):
        """拉取收藏夹：不做登录前置门槛（异步状态不可靠），让真实错误浮出水面。"""
        self.btn_refresh_folders.config(state="disabled")
        self._append_log("info", "正在拉取收藏夹列表…")
        threading.Thread(target=self._folders_worker, daemon=True).start()

    def _folders_worker(self):
        try:
            cookies = load_cookies(cookies_path(self.cfg))
            if not cookies or not cookies.get("SESSDATA"):
                self.q.put(("folders_error", "尚未登录或登录态丢失，请点右上角「扫码登录」", None))
                return
            client = _client(self.cfg)
            me = client.me()  # 顺带校验登录态，错误信息最准确
            folders = client.list_folders(int(me["mid"]))
            self.q.put(("folders", folders, None))
        except Exception as e:
            self.q.put(("folders_error", str(e), None))

    def _on_folders(self, folders, _):
        self.btn_refresh_folders.config(state="normal")
        tree = self.tree_folders
        tree.delete(*tree.get_children())
        self._sel_folder_ids = set()
        if not folders:
            self._append_log("warn", "没有取到收藏夹（账号可能还没有建夹子）")
            return
        saved = set(self.store.setting_get("folders") or [])
        for f in folders:
            if not isinstance(f, dict) or f.get("id") is None:
                continue  # 防御异常条目，不让单个脏数据炸掉整个流程
            fid = int(f["id"])
            sel = fid in saved
            if sel:
                self._sel_folder_ids.add(fid)
            tree.insert(
                "", "end", iid=str(fid),
                values=("✓" if sel else "", f["title"], f["media_count"], fid),
            )
        self._append_log("success", f"已拉取 {len(folders)} 个收藏夹：点第一列 ✓ 勾选，再点「开始同步」")

    def _on_folders_error(self, msg, _):
        self.btn_refresh_folders.config(state="normal")
        self._append_log("error", f"拉取收藏夹失败: {msg}")
        messagebox.showerror(
            "拉取收藏夹失败",
            f"{msg}\n\n"
            "排查提示：\n"
            "· 提示登录相关 → 点右上角「扫码登录」重新登录\n"
            "· 提示风控/请求频繁 → 等几分钟再点一次\n"
            "· 其他网络错误 → 检查代理/网络后重试",
        )

    def _toggle_folder(self, event):
        iid = self.tree_folders.identify_row(event.y)
        if not iid:
            return
        fid = int(iid)
        vals = list(self.tree_folders.item(iid, "values"))
        if fid in self._sel_folder_ids:
            self._sel_folder_ids.discard(fid)
            vals[0] = ""
        else:
            self._sel_folder_ids.add(fid)
            vals[0] = "✓"
        self.tree_folders.item(iid, values=vals)

    def _select_all_folders(self):
        for iid in self.tree_folders.get_children():
            vals = list(self.tree_folders.item(iid, "values"))
            vals[0] = "✓"
            self.tree_folders.item(iid, values=vals)
            self._sel_folder_ids.add(int(iid))

    def start_sync(self):
        if self._sync_busy:
            return
        cookies = load_cookies(cookies_path(self.cfg))
        if not cookies or not cookies.get("SESSDATA"):
            messagebox.showwarning("尚未登录", "请先点右上角「扫码登录」")
            return
        use_all = False  # 保持简单：勾哪个同步哪个
        ids = sorted(self._sel_folder_ids)
        if not ids:
            messagebox.showwarning("还没选择", "请先在列表第一列勾选要同步的收藏夹")
            return
        self.store.setting_set("folders", ids)
        limit_raw = self.var_sync_limit.get().strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        no_llm = not self.var_sync_llm.get()

        self._sync_busy = True
        self._sync_btn.config(state="disabled")
        self._append_log("rule", "开始同步")
        threading.Thread(
            target=self._sync_worker, args=(use_all, no_llm, limit), daemon=True
        ).start()

    def _sync_worker(self, use_all, no_llm, limit):
        from .commands import sync as sync_mod

        ns = SimpleNamespace(
            config=None, folder=None, all=use_all, limit=limit,
            no_subtitles=False, no_llm=no_llm,
        )
        try:
            rc = sync_mod.run(ns)
            self.q.put(("sync_done", rc, None))
        except Exception as e:
            self.q.put(("log", "error", f"同步异常: {e}"))
            self.q.put(("sync_done", 1, None))

    def _on_sync_done(self, rc, _):
        self._sync_busy = False
        self._sync_btn.config(state="normal")
        if rc == 0:
            self._append_log("success", "同步流程结束 ✔ 可以去「复习」页看看新卡片")
        else:
            self._append_log("error", "同步未完成，请查看上方日志")
        self.refresh_all()

    # ---------------------------------------------------------------- 复习

    def start_review(self):
        today = date.today().isoformat()
        maxn = int((self.cfg.get("review") or {}).get("max_per_session", 30))
        self._review_cards = self.store.due_items(today, maxn)
        self._review_idx = 0
        self._undo_snapshot = None
        self.btn_undo.config(state="disabled")
        self.show_view("review")
        if not self._review_cards:
            nxt = self.store.next_due_date()
            pending = self.store.promotable_count(today)
            self.var_r_progress.set(
                "今天没有到期卡片 🎉" + (f" 下一批到期: {nxt}" if nxt else "（先去同步收藏夹）")
            )
            self.var_r_title.set("——")
            self.var_r_meta.set("")
            self.var_r_oneliner.set("")
            self.var_r_quiz.set("")
            self._set_answer_text("（无内容）")
            self.btn_reveal.config(state="disabled")
            for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
                b.config(state="disabled")
            if pending:
                self.btn_promote.config(
                    text=f"📅  有 {pending} 张新卡排在之后 —— 点此提前到今天学习"
                )
                self.btn_promote.pack(fill="x", pady=(8, 0))
            else:
                self.btn_promote.pack_forget()
            return
        self.btn_promote.pack_forget()
        self._show_card()

    def _promote_and_review(self):
        n = self.store.promote_new_cards(date.today().isoformat())
        self._append_log("info", f"已把 {n} 张新卡片提前到今天")
        self.btn_promote.pack_forget()
        self.start_review()

    def _show_card(self):
        v = self._review_cards[self._review_idx]
        card = _load_card(v)
        self._current_bvid = v["bvid"]
        total = len(self._review_cards)
        self.var_r_title.set(v["title"])
        self.var_r_meta.set(f"UP: {v['upper_name']}    收藏夹: {v['folder_title']}")
        self.var_r_oneliner.set(
            card.get("one_liner") or ((v["intro"] or "")[:90]) or "（暂无摘要，凭标题回忆）"
        )
        if (v["reps"] or 0) == 0:
            # 新卡首次学习：没有可回忆的旧记忆，直接展示内容，读完自评
            self.var_r_progress.set(f"🆕 新卡 {self._review_idx + 1}/{total}（首次学习）")
            self.var_r_quiz.set("新卡片：通读下方内容后，凭感觉评估自己能记住多久")
            self._revealed = True
            self._fill_answer(v, card)
            self.btn_reveal.config(state="disabled")
            for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
                b.config(state="normal")
        else:
            self.var_r_progress.set(
                f"第 {self._review_idx + 1}/{total} 张 · 记过 {v['reps']} 次 · 忘过 {v['lapses']} 次"
            )
            quiz = (card.get("quiz") or [{}])[0].get("question", "")
            self.var_r_quiz.set(f"自测：{quiz}" if quiz else "先在脑中回忆这期视频讲了什么…")
            self._set_answer_text("（先自己回忆，再点「显示答案」）")
            self._revealed = False
            self.btn_reveal.config(state="normal")
            for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
                b.config(state="disabled")

    def reveal_answer(self):
        if self._revealed or self._review_idx >= len(self._review_cards):
            return
        self._revealed = True
        v = self._review_cards[self._review_idx]
        self._fill_answer(v, _load_card(v))
        self.btn_reveal.config(state="disabled")
        for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
            b.config(state="normal")

    def _fill_answer(self, v, card: dict):
        source = card.get("source")
        lines = []
        if source == "intro":
            lines.append("ℹ 本卡由标题+简介生成（视频无字幕），要点为看点预告")
        elif source == "title_only":
            lines.append("ℹ 本视频暂无字幕和简介，建议点上方「🌐 重看视频」直接观看")
        for k in card.get("key_points") or []:
            lines.append(f"• {k}")
        for q in card.get("quiz") or []:
            if q.get("question"):
                lines.append(f"\n自测：{q['question']}")
                if q.get("answer"):
                    lines.append(f"答案：{q['answer']}")
        if card.get("keywords"):
            lines.append("\n关键词：" + " / ".join(card["keywords"]))
        if not lines:
            lines = [v["intro"] or "（该视频暂无字幕与摘要，可凭标题回忆后评分）"]
        self._set_answer_text("\n".join(lines))

    def _grade(self, grade: int):
        if self._review_idx >= len(self._review_cards):
            return
        v = self._review_cards[self._review_idx]
        row = self.store.get_review_state(v["bvid"])
        self._undo_snapshot = (v["bvid"], dict(row) if row else None)
        base = dict(row) if row else new_state(date.today().isoformat())
        state = apply_review(base, grade, date.today())
        self.store.save_review_state(v["bvid"], state)
        self.btn_undo.config(state="normal")
        label = {GRADE_OK: "记得", GRADE_FUZZY: "模糊", GRADE_FORGOT: "忘了"}[grade]
        self._append_log(
            "info",
            f"[{label}] {v['title'][:36]} → 下次 {state['due_date']}（隔 {state['interval_days']} 天）",
        )
        self._advance()

    def _undo_grade(self):
        """撤销最近一次评分：恢复该卡原有排期并回到这张卡。"""
        if not self._undo_snapshot or not self._review_cards:
            return
        bvid, prev = self._undo_snapshot
        if prev:
            self.store.save_review_state(bvid, prev)
        else:
            self.store.save_review_state(bvid, new_state(date.today().isoformat()))
        self._undo_snapshot = None
        self.btn_undo.config(state="disabled")
        target = next(
            (i for i, c in enumerate(self._review_cards) if c["bvid"] == bvid), None
        )
        if target is None:
            self._refresh_home()
            return
        self._review_idx = target
        self._append_log("info", "已撤销上一次评分")
        self._show_card()

    def _review_key(self, event):
        """复习页快捷键：空格/回车显示答案，1/2/3 评分，S 跳过。输入框内打字不触发。"""
        if self._active_view != "review":
            return
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, ttk.Entry, tk.Text)):
            return
        ch = (event.char or "").lower()
        if ch in (" ", "\r"):
            self.reveal_answer()
        elif ch == "1" and self._revealed:
            self._grade(GRADE_FORGOT)
        elif ch == "2" and self._revealed:
            self._grade(GRADE_FUZZY)
        elif ch == "3" and self._revealed:
            self._grade(GRADE_OK)
        elif ch == "s":
            self._skip_card()

    def _skip_card(self):
        if not self._review_cards or self._review_idx >= len(self._review_cards):
            return  # 没有进行中的会话时忽略（快捷键 S / 按钮误触）
        self._append_log("info", "已跳过一张（不计入复习）")
        self._advance()

    def _advance(self):
        self._review_idx += 1
        if self._review_idx < len(self._review_cards):
            self._show_card()
        else:
            remaining = self.store.due_count(date.today().isoformat())
            self.var_r_progress.set(
                f"本轮复习完成 🎉 今日剩余到期 {remaining} 张"
                if remaining
                else "本轮复习完成，今天的卡片全部清空 🎉"
            )
            self.var_r_title.set("——")
            self.var_r_meta.set("")
            self.var_r_oneliner.set("休息一下，明天再来～")
            self.var_r_quiz.set("")
            self._set_answer_text("（无内容）")
            # 会话结束：让不可用的按钮真正置灰，避免"还能点"的错觉
            self.btn_reveal.config(state="disabled")
            for b in (self.btn_forgot, self.btn_fuzzy, self.btn_ok):
                b.config(state="disabled")
            self._undo_snapshot = None
            self.btn_undo.config(state="disabled")
            self.refresh_all()

    def _set_answer_text(self, text: str):
        self.txt_answer.config(state="normal")
        self.txt_answer.delete("1.0", "end")
        self.txt_answer.insert("1.0", text)
        self.txt_answer.config(state="disabled")

    def _open_current_video(self):
        bvid = getattr(self, "_current_bvid", None)
        if bvid:
            webbrowser.open(f"https://www.bilibili.com/video/{bvid}")

    # ---------------------------------------------------------------- 卡片库

    def fill_missing_summaries(self):
        """后台补齐缺失摘要（不依赖登录态，只走本地库 + AI）。"""
        if self._fill_busy:
            return
        self._fill_busy = True
        self.btn_fill.config(state="disabled")
        self._append_log("rule", "🤖 补齐缺失摘要")
        self._append_log(
            "info", "三档策略：有字幕精摘 → 无字幕批量轻摘（8条/次） → 无信息零AI兜底"
        )
        self._append_log(
            "info", "提示：轻摘卡之后会被 sync 拉到的字幕摘要自动覆盖升级"
        )

        def worker():
            from .commands.sync import fill_summaries

            cfg, _ = config_mod.load_config()
            store = Store(db_path(cfg))
            try:
                n = fill_summaries(store, cfg, 100)
                self.q.put(("fill_done", n, None))
            except Exception as e:
                self.q.put(("log", "error", f"补齐异常: {e}"))
                self.q.put(("fill_done", -1, None))
            finally:
                store.close()

        threading.Thread(target=worker, daemon=True).start()

    def _on_fill_done(self, n, _):
        self._fill_busy = False
        self.btn_fill.config(state="normal")
        if n and n > 0:
            self._append_log(
                "success", f"摘要补齐完成：本次新增 {n} 张；若还有缺漏，再点一次即可"
            )
        elif n == 0:
            self._append_log("success", "没有需要补的摘要（全部齐了）✔")
        else:
            self._append_log("error", "补齐未完成，请查看上方日志")
        self.refresh_cards()
        self._refresh_home()

    def refresh_cards(self):
        tree = self.tree_cards
        tree.delete(*tree.get_children())
        today = date.today().isoformat()
        flt = self.var_card_filter.get()
        badge = {
            "新卡": "🆕 新卡",
            "今日到期": "🔥 今日到期",
            "已逾期": "⚠ 已逾期",
            "长期记忆": "🌳 长期记忆",
            "复习中": "🔁 复习中",
        }
        shown = 0
        for r in self.store.all_cards():
            status = self._card_status(r, today)
            if flt != "全部" and status != flt:
                continue
            interval = r["interval_days"]
            tree.insert(
                "", "end", iid=r["bvid"],
                values=(
                    badge.get(status, status), r["title"], r["upper_name"],
                    r["due_date"] or "—",
                    f"{interval:g}" if interval is not None else "—",
                ),
            )
            shown += 1
        self.var_card_count.set(f"共 {shown} 张")

    @staticmethod
    def _card_status(r, today: str) -> str:
        """返回纯文本状态（与筛选器选项一致），展示时再加 emoji。"""
        reps = r["reps"] or 0
        due = r["due_date"]
        if reps == 0:
            return "新卡"
        if due and due < today:
            return "已逾期"
        if due == today:
            return "今日到期"
        if (r["interval_days"] or 0) >= 21:
            return "长期记忆"
        return "复习中"

    def _open_card_detail(self, _event):
        iid = self.tree_cards.focus()
        if iid:
            self._open_detail(iid)

    def _promote_one(self, bvid: str, win):
        self.store.set_due_date(bvid, date.today().isoformat())
        self._append_log("info", f"已把卡片提前到今天复习：{bvid}")
        win.destroy()
        self.refresh_cards()
        self._refresh_home()

    # ---------------------------------------------------------------- 统计与导出

    def _build_page_stats(self, f):
        wrap = tk.Frame(f, bg=C_PAGE)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 4))

        kv = tk.Frame(wrap, bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER)
        kv.pack(fill="x")
        kin = tk.Frame(kv, bg=C_CARD)
        kin.pack(fill="x", padx=16, pady=10)
        self._stat_kv_vars = {
            "lapses": tk.StringVar(value="0"),
            "avg": tk.StringVar(value="0"),
            "mature": tk.StringVar(value="0"),
            "learning": tk.StringVar(value="0"),
        }
        for i, (label, key) in enumerate((
            ("忘过总次数", "lapses"),
            ("平均记忆间隔(天)", "avg"),
            ("长期记忆卡片", "mature"),
            ("复习进行中", "learning"),
        )):
            col = tk.Frame(kin, bg=C_CARD)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, textvariable=self._stat_kv_vars[key], font=(FONT, 15, "bold"),
                     bg=C_CARD, fg=C_TEXT).pack(anchor="w")
            tk.Label(col, text=label, font=(FONT, 9), bg=C_CARD, fg=C_TEXT2).pack(anchor="w")
            if i < 3:
                tk.Frame(kin, bg=C_BORDER, width=1).pack(side="left", fill="y", padx=14)

        c1 = ttk.Labelframe(wrap, text=" 未来 7 天到期分布 ", style="Card.TLabelframe", padding=8)
        c1.pack(fill="x", pady=(12, 0))
        self.chart_due = tk.Canvas(c1, height=150, bg=C_CARD, highlightthickness=0)
        self.chart_due.pack(fill="x")
        self.chart_due.bind("<Configure>", lambda e: self._redraw_charts())

        c2 = ttk.Labelframe(wrap, text=" 近 14 天复习活跃度 ", style="Card.TLabelframe", padding=8)
        c2.pack(fill="x", pady=(12, 0))
        self.chart_activity = tk.Canvas(c2, height=130, bg=C_CARD, highlightthickness=0)
        self.chart_activity.pack(fill="x")
        self.chart_activity.bind("<Configure>", lambda e: self._redraw_charts())

    def refresh_stats(self):
        c = self.store.counts()
        life = self.store.lifetime_stats()
        self._stat_kv_vars["lapses"].set(str(life["lapses"]))
        self._stat_kv_vars["avg"].set(f"{life['avg_interval']:g}")
        self._stat_kv_vars["mature"].set(str(c["mature"]))
        self._stat_kv_vars["learning"].set(str(c["learning"]))
        overdue, due_series = self.store.due_by_day(date.today().isoformat(), days=7)
        activity = self.store.review_activity(days=14)
        today = date.today().strftime("%m-%d")
        due_data = []
        if overdue:
            due_data.append(("已逾期", overdue, C_DANGER))
        for i, (lbl, n) in enumerate(due_series):
            color = C_WARN if lbl == today else C_INFO
            due_data.append((lbl, n, color))
        act_data = [(lbl, n, C_OK) for lbl, n in activity]
        self._chart_data = {"due": due_data, "activity": act_data}
        self._redraw_charts()

    def _redraw_charts(self):
        if not self._chart_data:
            return
        self._draw_bars(self.chart_due, self._chart_data["due"])
        self._draw_bars(self.chart_activity, self._chart_data["activity"])

    @staticmethod
    def _draw_bars(canvas, data: list[tuple[str, int, str]]):
        canvas.delete("all")
        w = int(canvas.winfo_width() or 760)
        h = int(canvas.winfo_height() or 150)
        if not data:
            canvas.create_text(w // 2, h // 2, text="暂无数据", font=(FONT, 10), fill=C_TEXT3)
            return
        maxv = max(v for _, v, _ in data) or 1
        n = len(data)
        gap = max(8, w // 60)
        bw = max(16, min(46, (w - 28 - gap * (n - 1)) // n))
        baseline = h - 26
        top = 16
        x = 14
        for label, value, color in data:
            bh = int((baseline - top) * value / maxv)
            canvas.create_rectangle(x, baseline - bh, x + bw, baseline,
                                    fill=color, outline="")
            if value:
                canvas.create_text(x + bw / 2, baseline - bh - 8, text=str(value),
                                   font=(FONT, 9), fill=C_TEXT2)
            canvas.create_text(x + bw / 2, baseline + 11, text=label,
                               font=(FONT, 9), fill=C_TEXT2)
            x += bw + gap

    def export_anki(self):
        if getattr(self, "_anki_busy", False):
            return
        self._anki_busy = True
        self.btn_anki.config(state="disabled")
        self._append_log("rule", "📤 导出 Anki 牌组")

        def worker():
            from .commands import anki_export
            from .config import load_config as _lc
            from .paths import db_path as _dbp

            cfg, _ = _lc()
            store = Store(_dbp(cfg))
            try:
                rc = anki_export.run(SimpleNamespace(config=None, out=None, deck=None))
                self.q.put(("anki_done", rc, None))
            except Exception as e:
                self.q.put(("log", "error", f"导出异常: {e}"))
                self.q.put(("anki_done", 1, None))
            finally:
                store.close()

        threading.Thread(target=worker, daemon=True).start()

    def _on_anki_done(self, rc, _):
        self._anki_busy = False
        self.btn_anki.config(state="normal")
        if rc == 0:
            out = resolve_data_dir(self.cfg) / "exports"
            self._append_log("info", f"文件位置: {out}")
            if messagebox.askyesno("导出成功", "Anki 牌组已导出，打开所在文件夹？"):
                os.startfile(str(out))  # noqa: S606
        else:
            self._append_log("error", "导出失败，请查看上方日志")

    # ---------------------------------------------------------------- 搜索

    def do_search(self):
        query = self.var_search.get().strip()
        tree = self.tree_search
        tree.delete(*tree.get_children())
        if not query:
            return
        rows = self.store.search(query, limit=20)
        if not rows:
            self._append_log("info", f"没有找到包含“{query}”的收藏")
            return
        for r in rows:
            snip = (r["snip"] if "snip" in r.keys() and r["snip"] else None) or make_snippet(
                r, query
            )
            tree.insert(
                "", "end", iid=r["bvid"],
                values=(r["title"], r["upper_name"], r["folder_title"], snip.strip()[:120]),
            )

    def _open_search_detail(self, _event):
        iid = self.tree_search.focus()
        if iid:
            self._open_detail(iid)

    def _open_detail(self, bvid: str):
        """完整卡片详情（搜索页与卡片库共用）。"""
        v = self.store.get_video(bvid)
        if v is None:
            return
        card = {}
        if v["summary_json"]:
            try:
                card = json.loads(v["summary_json"]) or {}
            except Exception:
                card = {}
        st = self.store.get_review_state(v["bvid"])

        win = tk.Toplevel(self.root)
        win.title(v["title"][:40])
        win.geometry("640x540")
        win.configure(bg=C_PAGE)
        txt = tk.Text(win, wrap="word", relief="flat", background=C_CARD,
                      foreground=C_TEXT, padx=14, pady=12,
                      highlightthickness=1, highlightbackground=C_BORDER)
        scroll = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=8)
        txt.pack(fill="both", expand=True, padx=(8, 0), pady=8)
        lines = [f"【{v['title']}】", f"UP: {v['upper_name']}    收藏夹: {v['folder_title']}", ""]
        if card.get("one_liner"):
            lines.append(f"一句话：{card['one_liner']}")
            lines.append("")
        for k in card.get("key_points") or []:
            lines.append(f"• {k}")
        for q in card.get("quiz") or []:
            if q.get("question"):
                lines.append(f"\n自测：{q['question']}")
                if q.get("answer"):
                    lines.append(f"答案：{q['answer']}")
        if card.get("keywords"):
            lines.append("\n关键词：" + " / ".join(card["keywords"]))
        if v["transcript"]:
            lines.append(f"\n—— 字幕节选 ——\n{v['transcript'][:1500]}…")
        elif v["subtitle_note"]:
            lines.append(f"\n（{v['subtitle_note']}）")
        if st:
            lines.append(
                f"\n复习状态：到期 {st['due_date']} · 记过 {st['reps']} 次 · 忘过 {st['lapses']} 次"
                f" · 当前间隔 {st['interval_days']} 天"
            )
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")

        btns = ttk.Frame(win, style="Card.TFrame")
        btns.pack(pady=6)
        today = date.today().isoformat()
        if st and st["due_date"] and st["due_date"] > today:
            ttk.Button(
                btns, text="📅 提前到今天复习",
                command=lambda: self._promote_one(v["bvid"], win),
            ).pack(side="left", padx=4)
        ttk.Button(
            btns, text="🌐 在 B 站打开这个视频",
            command=lambda: webbrowser.open(f"https://www.bilibili.com/video/{v['bvid']}"),
        ).pack(side="left", padx=4)

    # ---------------------------------------------------------------- 设置

    def save_settings(self):
        try:
            config_mod.update_config_values(
                self.cfg_path,
                {
                    "api_key": self.var_set_key.get().strip(),
                    "base_url": self.var_set_base.get().strip(),
                    "model": self.var_set_model.get().strip(),
                },
            )
            self.cfg, _ = config_mod.load_config()
            messagebox.showinfo("已保存", f"配置已写入：\n{self.cfg_path}")
            self._append_log("success", "AI 配置已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def save_push_settings(self):
        try:
            config_mod.update_config_values(
                self.cfg_path,
                {"serverchan_sendkey": self.var_set_sendkey.get().strip()},
                insert_section="[notify]",
            )
            self.cfg, _ = config_mod.load_config()
            self._append_log("success", "推送配置已保存")
            messagebox.showinfo("已保存", "微信推送配置已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _schtasks(self, *args):
        # schtasks 输出为控制台代码页（zh-CN 为 GBK）；显式指定解码避免 UTF-8 模式下崩溃
        return subprocess.run(
            ["schtasks", *args], capture_output=True,
            encoding="gbk", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _refresh_task_status(self):
        r = self._schtasks("/Query", "/TN", TASK_NAME)
        self.var_task_status.set("已开启 ✔" if r.returncode == 0 else "未开启")

    def create_task(self):
        hhmm = self.var_task_time.get().strip() or "09:30"
        # 计划任务优先用 pythonw：跑提醒时不闪黑窗
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        runner = pyw if pyw.exists() else exe
        tr = f'"{runner}" -m bili_fav_review due --notify'
        r = self._schtasks(
            "/Create", "/F", "/SC", "DAILY", "/ST", hhmm, "/TN", TASK_NAME, "/TR", tr
        )
        if r.returncode == 0:
            messagebox.showinfo("已开启", f"每天 {hhmm} 会弹出到期提醒")
        else:
            messagebox.showerror("创建失败", r.stderr or r.stdout)
        self._refresh_task_status()

    def remove_task(self):
        r = self._schtasks("/Delete", "/TN", TASK_NAME, "/F")
        if r.returncode == 0:
            messagebox.showinfo("已移除", "每日提醒已关闭")
        self._refresh_task_status()

    def _open_data_dir(self):
        path = str(resolve_data_dir(self.cfg))
        os.makedirs(path, exist_ok=True)
        os.startfile(path)  # noqa: S606 — Windows 资源管理器

    # ---------------------------------------------------------------- 帮助

    def open_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用指南")
        win.geometry("700x560")
        win.transient(self.root)
        win.configure(bg=C_PAGE)
        txt = tk.Text(win, wrap="word", relief="flat", background=C_CARD,
                      foreground=C_TEXT, padx=16, pady=12,
                      highlightthickness=1, highlightbackground=C_BORDER)
        scroll = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        txt.pack(fill="both", expand=True, padx=(8, 0), pady=8)
        txt.insert("1.0", HELP_TEXT)
        txt.config(state="disabled")
        btns = ttk.Frame(win)
        btns.pack(pady=6)
        ttk.Button(btns, text="打开完整指南文件", command=self._open_guide_file).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="打开数据文件夹", command=self._open_data_dir).pack(
            side="left", padx=4
        )

    def _open_guide_file(self):
        candidates = [
            Path(__file__).resolve().parent.parent / "使用指南.md",
            Path.cwd() / "使用指南.md",
        ]
        for p in candidates:
            if p.exists():
                os.startfile(str(p))  # noqa: S606
                return
        messagebox.showinfo(
            "未找到指南文件",
            "完整版《使用指南.md》未随安装分发（开源仓库里才有），\n本窗口内已是速览版指南。",
        )

    # ---------------------------------------------------------------- 退出

    def _on_close(self):
        ui.set_sink(None)
        try:
            self.store.close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run_gui() -> int:
    """图形界面入口；异常兜底写日志文件，避免 pythonw 下无声崩溃。"""
    if not _TK_OK:
        ui.error("当前 Python 缺少 tkinter 图形组件（python.org 官方安装包自带，重装时勾选 tcl/tk 即可）")
        return 1
    threading.excepthook = _thread_excepthook  # 后台线程异常不进黑洞
    try:
        app = App()
    except Exception:
        import traceback

        err = traceback.format_exc()
        _append_error_file(err)
        try:
            messagebox.showerror("启动失败", f"界面启动失败，详情见 gui_error.log\n\n{err[-500:]}")
        except Exception:
            print(err)
        return 1
    app.run()
    return 0
