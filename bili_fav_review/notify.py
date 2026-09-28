"""Windows Toast 通知（可选依赖 win11toast；缺失时静默降级为控制台输出）。"""


def notify(title: str, message: str) -> bool:
    try:
        from win11toast import toast

        toast(title, message, duration="short")
        return True
    except Exception:
        return False
