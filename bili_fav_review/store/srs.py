"""遗忘曲线调度（SM-2 简化版）。

三种自评：忘了(0) / 模糊(1) / 记得(2)
- 记得：首次成功间隔 2 天，之后 间隔×ease；ease +0.05（上限 3.0）
- 模糊：间隔 ×0.6（至少 1 天）；ease -0.05
- 忘了：重置为 1 天后再复习；ease -0.20（下限 1.3）
间隔上限 365 天。数值经验上偏向"多见面"，适合碎片化复习。
"""

from datetime import date, timedelta

GRADE_FORGOT = 0
GRADE_FUZZY = 1
GRADE_OK = 2

MIN_EASE = 1.3
MAX_EASE = 3.0
MAX_INTERVAL = 365.0


def new_state(due_date: str) -> dict:
    """新卡片初始状态，due_date 为 ISO 日期字符串。"""
    return {
        "ease": 2.3,
        "interval_days": 0.0,
        "reps": 0,
        "lapses": 0,
        "due_date": due_date,
        "last_review": None,
    }


def apply_review(state: dict, grade: int, today: date) -> dict:
    s = dict(state)
    if grade == GRADE_OK:
        s["reps"] = int(s.get("reps", 0)) + 1
        if s["reps"] == 1:
            s["interval_days"] = 2.0
        else:
            s["interval_days"] = s.get("interval_days", 1.0) * s.get("ease", 2.3)
        s["ease"] = min(MAX_EASE, s.get("ease", 2.3) + 0.05)
    elif grade == GRADE_FUZZY:
        s["interval_days"] = max(1.0, s.get("interval_days", 0.0) * 0.6)
        s["ease"] = max(MIN_EASE, s.get("ease", 2.3) - 0.05)
    else:
        s["lapses"] = int(s.get("lapses", 0)) + 1
        s["reps"] = 0
        s["interval_days"] = 1.0
        s["ease"] = max(MIN_EASE, s.get("ease", 2.3) - 0.20)

    s["interval_days"] = round(min(MAX_INTERVAL, s["interval_days"]), 1)
    s["due_date"] = (today + timedelta(days=s["interval_days"])).isoformat()
    s["last_review"] = int(today.strftime("%Y%m%d"))
    return s
