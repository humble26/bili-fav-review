"""输出封装：终端下有 rich 用 rich；图形前端可通过 set_sink 接管全部输出。"""

import sys

try:
    from rich.console import Console as _RC
    from rich.panel import Panel as _Panel
    from rich.table import Table as _Table
    from rich.text import Text as _Text

    _console = _RC(highlight=False)
    _HAS_RICH = True
except Exception:  # pragma: no cover - rich 缺失时的兜底
    _HAS_RICH = False

# 前端接管口：set_sink(fn) 后，info/success/warn/error/rule 都改为调用 fn(level, text)
_sink = None


def set_sink(fn) -> None:
    global _sink
    _sink = fn


def _stdout_ok() -> bool:
    # pythonw（无控制台窗口）下 sys.stdout 为 None，print 会直接崩
    return sys.stdout is not None


def info(msg: str) -> None:
    if _sink is not None:
        _sink("info", str(msg))
        return
    if not _stdout_ok():
        return
    (_console.print if _HAS_RICH else print)(msg)


def success(msg: str) -> None:
    if _sink is not None:
        _sink("success", str(msg))
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        _console.print(f"[green]✔ {msg}[/green]")
    else:
        print(f"[OK] {msg}")


def warn(msg: str) -> None:
    if _sink is not None:
        _sink("warn", str(msg))
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        _console.print(f"[yellow]⚠ {msg}[/yellow]")
    else:
        print(f"[!] {msg}")


def error(msg: str) -> None:
    if _sink is not None:
        _sink("error", str(msg))
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        _console.print(f"[red]✘ {msg}[/red]")
    else:
        print(f"[X] {msg}")


def rule(title: str = "") -> None:
    if _sink is not None:
        _sink("rule", str(title or ""))
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        _console.rule(title)
    else:
        print(f"──── {title} " + "─" * max(0, 40 - len(title)))


def kv_table(title: str, rows: list[tuple[str, str]]) -> None:
    """两列 key-value 表格。"""
    if _sink is not None:
        _sink("info", f"== {title} ==")
        for k, v in rows:
            _sink("info", f"  {k}: {v}")
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        t = _Table(title=title, show_header=False, pad_edge=False)
        t.add_column(style="cyan", no_wrap=True)
        t.add_column()
        for k, v in rows:
            t.add_row(k, str(v))
        _console.print(t)
    else:
        print(f"== {title} ==")
        for k, v in rows:
            print(f"  {k}: {v}")


def data_table(headers: list[str], rows: list[list], title: str = "") -> None:
    if _sink is not None:
        if title:
            _sink("info", f"== {title} ==")
        _sink("info", " | ".join(headers))
        for r in rows:
            _sink("info", " | ".join(str(c) for c in r))
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        t = _Table(title=title or None)
        for h in headers:
            t.add_column(h)
        for r in rows:
            t.add_row(*[str(c) for c in r])
        _console.print(t)
    else:
        if title:
            print(f"== {title} ==")
        print(" | ".join(headers))
        for r in rows:
            print(" | ".join(str(c) for c in r))


def panel(title: str, lines: list[str], subtitle: str = "") -> None:
    if _sink is not None:
        _sink("rule", title + (f"  ({subtitle})" if subtitle else ""))
        for line in lines:
            _sink("info", line)
        return
    if not _stdout_ok():
        return
    if _HAS_RICH:
        body = _Text()
        for i, line in enumerate(lines):
            if i:
                body.append("\n")
            body.append(line)
        _console.print(_Panel(body, title=title, subtitle=subtitle or None))
    else:
        print(f"┌─ {title} " + ("│ " + subtitle if subtitle else ""))
        for line in lines:
            print(f"│ {line}")
        print("└" + "─" * 50)


def bar(n: int, width: int = 20) -> str:
    filled = "█" * round(n / 100 * width)
    return filled + "·" * (width - len(filled))
