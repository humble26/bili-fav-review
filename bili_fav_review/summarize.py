"""LLM 摘要：把字幕整理成可复习的卡片。

走 OpenAI 兼容的 chat/completions 接口（GLM / DeepSeek / Moonshot / ollama 均可），
不依赖 openai SDK，减少环境问题。LLM 只负责整理，不做事件判定。
"""

import json
import re

import requests

SYSTEM_PROMPT = """你是一名中文知识整理助手。用户给你一个B站视频的标题、简介和字幕文本，\
请把它整理成复习卡片。只输出一个 JSON 对象，不要输出任何其他文字或代码块标记。\
字段要求：
- one_liner: 一句话概括视频核心内容，不超过50字
- key_points: 3到6条要点数组，每条不超过50字，讲清"讲了什么/结论是什么"
- keywords: 最多6个关键词数组
- quiz: 1到3个自测问题数组，每项含 question（提问）和 answer（答案要点，不超过80字），\
问题要能检验是否真的看懂了视频"""

RETRYABLE = (requests.Timeout, requests.ConnectionError)

INTRO_SYSTEM_PROMPT = """你是一名中文知识整理助手。用户给你若干B站视频的标题和简介。注意：没有视频正文，\
你并不知道视频实际讲了什么，只能归纳主题。请为每个视频生成一张"看点预告"式复习卡，\
只根据标题与简介归纳，不要编造视频里可能出现的具体细节、数据或结论。只输出一个 JSON 数组，\
不要任何其他文字，每个元素形如：
{"i": 序号, "one_liner": "主题概括，不超过40字", "key_points": ["看点1", "看点2", "看点3"], \
"keywords": ["关键词"], "quiz": [{"question": "看完这个视频应该能回答的一个问题", "answer": "观看后自行补充"}]}
key_points 给 2 到 4 条，简洁。"""


def _extract_json_array(text: str) -> list | None:
    """容错解析 LLM 输出里的 JSON 数组。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _extract_json(text: str) -> dict | None:
    """容错解析 LLM 输出里的 JSON（剥掉代码块围栏、前后闲话）。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _truncate(text: str, max_chars: int) -> str:
    sep = "\n…(中间部分省略)…\n"
    if len(text) <= max_chars:
        return text
    head = int((max_chars - len(sep)) * 0.7)
    tail = max_chars - len(sep) - head
    return text[:head] + sep + text[-tail:]


def _normalize(data: dict) -> dict:
    """补齐缺字段，保证下游拿到的结构稳定。"""
    def _strs(v):
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    quiz = []
    for q in data.get("quiz") or []:
        if isinstance(q, dict) and q.get("question"):
            quiz.append({"question": str(q["question"]), "answer": str(q.get("answer", ""))})
    return {
        "one_liner": str(data.get("one_liner", "")).strip(),
        "key_points": _strs(data.get("key_points"))[:6],
        "keywords": _strs(data.get("keywords"))[:6],
        "quiz": quiz[:3],
    }


def summarize(title: str, intro: str, transcript: str, llm_cfg: dict) -> dict:
    """调用 LLM 生成摘要卡片；失败抛异常，由调用方记录到 summary_error。"""
    url = llm_cfg["base_url"].rstrip("/") + "/chat/completions"
    user_content = (
        f"标题：{title}\n简介：{(intro or '')[:500]}\n"
        f"字幕全文：\n{_truncate(transcript, int(llm_cfg.get('max_transcript_chars', 9000)))}"
    )
    payload = {
        "model": llm_cfg["model"],
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {"Authorization": f"Bearer {llm_cfg['api_key']}"}
    timeout = int(llm_cfg.get("timeout", 120))

    last_err: Exception | None = None
    for _ in range(2):  # 重试一次（JSON 解析失败或网络抖动）
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = _extract_json(content)
            if data is None:
                last_err = ValueError(f"LLM 返回内容无法解析为 JSON: {content[:120]}")
                payload["temperature"] = 0.1
                continue
            return _normalize(data)
        except RETRYABLE as e:
            last_err = e
            continue
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            last_err = ValueError(f"LLM 响应格式异常: {e}")
            continue
    raise RuntimeError(f"摘要生成失败: {last_err}")


def summarize_intro_batch(items: list[dict], llm_cfg: dict) -> dict[int, dict]:
    """无字幕视频的批量轻摘：items = [{"i": 序号, "title": ..., "intro": ...}]。

    一次调用生成多张卡，返回 {序号: 卡片}。省请求次数、省 token 开销。
    """
    url = llm_cfg["base_url"].rstrip("/") + "/chat/completions"
    listing = "\n".join(
        f'{it["i"]}. 标题：{it["title"]}\n   简介：{(it["intro"] or "(无)")[:300]}'
        for it in items
    )
    payload = {
        "model": llm_cfg["model"],
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": INTRO_SYSTEM_PROMPT},
            {"role": "user", "content": f"共 {len(items)} 个视频：\n{listing}"},
        ],
    }
    headers = {"Authorization": f"Bearer {llm_cfg['api_key']}"}
    timeout = int(llm_cfg.get("timeout", 120))

    last_err: Exception | None = None
    for _ in range(2):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = _extract_json_array(content)
            if not data:
                last_err = ValueError(f"LLM 返回无法解析为数组: {content[:120]}")
                continue
            out: dict[int, dict] = {}
            for entry in data:
                if not isinstance(entry, dict) or "i" not in entry:
                    continue
                try:
                    idx = int(entry["i"])
                except (TypeError, ValueError):
                    continue
                card = _normalize(entry)
                card["i"] = idx
                out[idx] = card
            if out:
                return out
            last_err = ValueError("LLM 返回数组为空或无有效条目")
        except RETRYABLE as e:
            last_err = e
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            last_err = ValueError(f"LLM 响应格式异常: {e}")
    raise RuntimeError(f"批量摘要失败: {last_err}")
