"""Web 界面层：本地 HTTP 服务 + pywebview 原生窗口（替代原 tkinter 界面）。

业务逻辑一行不改：本层只把 store/* 与 commands/* 的能力暴露成 JSON 接口，
前端（static/ 下的 HTML/CSS/JS，零构建）负责呈现。
"""
