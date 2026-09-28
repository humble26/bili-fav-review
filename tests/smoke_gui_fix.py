"""一次性冒烟脚本：验证 v0.2.1 对「点了没反应」类问题的修复。运行后可删除。"""
import tkinter as tk

from bili_fav_review import gui as g

calls = []
g.messagebox.showerror = lambda *a, **k: calls.append(("error", a))
g.messagebox.showinfo = lambda *a, **k: calls.append(("info", a))
g.messagebox.showwarning = lambda *a, **k: calls.append(("warn", a))

app = g.App()


def log_has(s):
    return s in app.txt_log.get("1.0", "end")


def probe1():
    print("== T1: 处理器抛异常不杀死轮询器 ==")

    def bad(a, b):
        raise RuntimeError("模拟处理器崩溃")

    app._on_folders = bad
    app.q.put(("folders", [], None))
    app.q.put(("log", "info", "轮询器还活着"))
    app.root.after(800, probe2)


def probe2():
    assert log_has("处理 folders 时出错"), "异常未被捕获"
    assert log_has("轮询器还活着"), "轮询器已死（修复无效）"
    del app._on_folders  # 还原真实方法
    print("   PASS: 异常被捕获且轮询器存活")

    print("== T2: 未登录门槛移除，直接拉取（用真实登录态验证全链路） ==")
    app.refresh_folders()
    app.root.after(6000, probe3)


def probe3():
    assert log_has("正在拉取收藏夹列表"), "点击后连开始日志都没有"
    if log_has("已拉取"):
        print("   PASS: 真实登录态拉取成功（列表已填充）")
        assert str(app.btn_refresh_folders.cget("state")) != "disabled", "成功后按钮仍禁用"
    else:
        assert any(c[0] == "error" for c in calls), "失败但既没成功也没弹窗"
        print("   PASS: 失败时弹出了错误窗:", calls[-1][1][0][:60])

    print("== T3: 帮助窗口 ==")
    app.open_help()
    found = any(
        isinstance(w, tk.Toplevel) and w.title() == "使用指南"
        for w in app.root.winfo_children()
    )
    assert found, "帮助窗口未创建"
    print("   PASS")

    print("== T4: 登录成功后自动跳转收藏夹页并拉取 ==")
    app._on_login_success("12345", None)
    app.root.after(6000, probe4)


def probe4():
    assert log_has("正在拉取收藏夹列表"), "登录成功后未自动触发拉取"
    if log_has("已拉取"):
        print("   PASS: 自动拉取成功")
    else:
        assert any(c[0] == "error" for c in calls), "自动拉取既没成功也没报错"
        print("   PASS: 自动拉取失败时也有弹窗反馈（不再无声）")
    print("== GUI 修复冒烟全部通过 ==")
    app._on_close()


app.root.after(600, probe1)
app.run()
