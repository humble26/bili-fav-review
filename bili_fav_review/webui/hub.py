"""界面事件中枢：后台线程 put，前端轮询 /api/events 取增量。

对应旧 tkinter 版的 queue.Queue + 120ms 轮询：所有网络/同步等耗时操作
都在后台线程跑，产生的日志、登录状态、二维码等按序入队，前端带上
自己的 seq 拉取增量即可，不需要跨线程调用界面。
"""

import threading


class EventHub:
    def __init__(self, keep: int = 400):
        self._lock = threading.Lock()
        self._seq = 0
        self._events: list[tuple[int, str, dict]] = []
        self._keep = keep

    def put(self, kind: str, payload: dict | None = None) -> int:
        with self._lock:
            self._seq += 1
            self._events.append((self._seq, kind, payload or {}))
            if len(self._events) > self._keep:
                del self._events[: -self._keep]
            return self._seq

    def since(self, seq: int) -> dict:
        with self._lock:
            events = [
                {"seq": s, "kind": k, "data": d} for s, k, d in self._events if s > seq
            ]
            return {"seq": self._seq, "events": events}
