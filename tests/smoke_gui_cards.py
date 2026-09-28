"""一次性冒烟：验证 v0.2.2 卡片库独立 + 新卡学习模式。运行后可保留作诊断。"""
import tkinter as tk

from bili_fav_review import gui as g

g.messagebox.showerror = lambda *a, **k: None
g.messagebox.showinfo = lambda *a, **k: None
g.messagebox.showwarning = lambda *a, **k: None

app = g.App()


def probe1():
    print("== T1: 复习入口（有空态引导 或 直接进入新卡学习） ==")
    app.start_review()
    if len(app._review_cards) == 0:
        assert str(app.btn_promote.winfo_manager()) == "pack", "空态时 promote 按钮未出现"
        print("   PASS: 空态出现按钮:", app.btn_promote.cget("text"))
        app._promote_and_review()
    else:
        print("   PASS: 今日已有到期卡，直接进入复习")
    assert len(app._review_cards) > 0, "复习队列仍为空"
    assert "新卡" in app.var_r_progress.get(), f"非新卡学习模式: {app.var_r_progress.get()}"
    answer = app.txt_answer.get("1.0", "end").strip()
    assert answer and "先自己回忆" not in answer, "新卡未直接展示内容"
    print("   PASS:", app.var_r_progress.get(), "| 卡片:", app.var_r_title.get()[:30])

    print("== T2: 评分一张后正常推进 ==")
    app._grade(2)  # 模糊
    assert app.var_r_title.get() not in ("", "——"), "评分后未推进"
    print("   PASS:", app.var_r_progress.get())

    print("== T3: 卡片库列表与筛选 ==")
    app.show_view("cards")  # 触发进入卡片库自动刷新
    app.root.after(500, probe2)


def probe2():
    n = len(app.tree_cards.get_children())
    assert n >= 3, f"卡片库行数异常: {n}"
    print(f"   PASS: 卡片库共 {n} 行")

    app.var_card_filter.set("新卡")
    app.refresh_cards()
    rows = app.tree_cards.get_children()
    assert rows, "筛选新卡后为空"
    for iid in rows:
        assert app.tree_cards.item(iid, "values")[0] == "🆕 新卡", iid
    print(f"   PASS: 筛选“新卡”得 {len(rows)} 行，徽章全部正确")

    print("== T4: 详情窗口（搜索页/卡片库共享） ==")
    app.tree_cards.selection_set(rows[0])
    app.tree_cards.focus(rows[0])
    app._open_card_detail(None)
    found = any(isinstance(w, tk.Toplevel) for w in app.root.winfo_children())
    assert found, "详情窗口未创建"
    print("   PASS")

    print("== T5: 首页到期分类统计 ==")
    app._refresh_home()
    assert app._stat_vars["total"].get().isdigit(), "磁贴数值异常"
    assert "开始复习" in app._home_btn_text.get() and "张" in app._home_btn_text.get(), app._home_btn_text.get()
    assert "新卡" in app.var_home_due.get() and "复习" in app.var_home_due.get(), app.var_home_due.get()
    print("   PASS:", app._home_btn_text.get(), "|", app.var_home_due.get())
    print("== T6: 字体择优 ==", app._font_note)

    print("== 卡片库/新卡学习 冒烟全部通过 ==")
    app._on_close()


app.root.after(700, probe1)
app.run()
