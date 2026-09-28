/* 界面基础设施：RPC 客户端、事件轮询、日志面板、通知、弹层、登录状态。
   与页面无关，供 app.js 与各视图共用（避免循环依赖）。 */

const TOKEN = new URLSearchParams(location.search).get("t") || "";
export const $ = (sel, root = document) => root.querySelector(sel);

export const state = { seq: 0, boot: null, view: null };

/* ---------------------------------------------------------------- RPC */

export async function rpc(method, params = {}) {
  const res = await fetch("/api/rpc", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-BFR-Token": TOKEN },
    body: JSON.stringify({ method, params }),
  });
  let payload = {};
  try { payload = await res.json(); } catch { /* 空响应 */ }
  if (!res.ok || !payload.ok) throw new Error(payload.error || `请求失败（HTTP ${res.status}）`);
  return payload.data;
}

/* ---------------------------------------------------------------- 日志面板 */

const LOG_CAP = 500;
let logCount = 0;

export function appendLog(level, text) {
  const body = $("#log-body");
  const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  const line = document.createElement("div");
  line.className = `log-line ${level || "info"}`;
  line.textContent = level === "rule" ? `────── ${text} ──────` : text;
  body.appendChild(line);
  if (++logCount > LOG_CAP) {
    body.removeChild(body.firstElementChild);
    logCount -= 1;
  }
  if (atBottom) body.scrollTop = body.scrollHeight;
}

export function clearLog() {
  $("#log-body").innerHTML = "";
  logCount = 0;
}

/* ---------------------------------------------------------------- 通知 */

export function toast(text, kind = "info", ms = 3200) {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/* ---------------------------------------------------------------- 弹层 */

let modalOnClose = null;

export function openModal({ title, body = "", actions = [], width = 520, onClose = null }) {
  const mask = $("#modal-root");
  const box = $("#modal-box");
  modalOnClose = onClose;
  box.style.width = `${width}px`;
  box.innerHTML = `
    <div class="modal-head">
      <h3>${escapeHtml(title)}</h3>
      <button class="modal-close" data-close title="关闭">✕</button>
    </div>
    <div class="modal-body">${body}</div>
    ${actions.length ? `<div class="modal-foot">${actions
      .map((a, i) => `<button class="btn ${a.kind || ""}" data-action="${i}">${escapeHtml(a.label)}</button>`)
      .join("")}</div>` : ""}`;
  mask.classList.remove("hidden");
  box.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeModal));
  box.querySelectorAll("[data-action]").forEach((b) => {
    b.onclick = async () => {
      const action = actions[Number(b.dataset.action)];
      try { await action.onClick?.(box); } catch (e) { toast(e.message, "error"); }
    };
  });
  return box;
}

export function closeModal() {
  const mask = $("#modal-root");
  if (mask.classList.contains("hidden")) return;
  mask.classList.add("hidden");
  $("#modal-box").innerHTML = "";
  const cb = modalOnClose;
  modalOnClose = null;
  try { cb?.(); } catch { /* 关闭回调不阻塞 */ }
}

/* ---------------------------------------------------------------- 事件订阅 */

const handlers = new Map(); // kind -> Set<fn>

export function onEvent(kind, fn) {
  if (!handlers.has(kind)) handlers.set(kind, new Set());
  handlers.get(kind).add(fn);
  return () => handlers.get(kind)?.delete(fn);
}

function emit(kind, data) {
  handlers.get(kind)?.forEach((fn) => {
    try { fn(data); } catch (e) { appendLog("error", `事件处理出错（${kind}）: ${e.message}`); }
  });
}

export function startPolling() {
  const tick = async () => {
    let delay = 450;
    try {
      const res = await fetch(`/api/events?since=${state.seq}&t=${encodeURIComponent(TOKEN)}`);
      if (res.ok) {
        const data = await res.json();
        state.seq = data.seq;
        for (const ev of data.events) {
          if (ev.kind === "log") appendLog(ev.data.level, ev.data.text);
          else emit(ev.kind, ev.data);
        }
      }
    } catch {
      delay = 1200; // 服务忙碌/重启时退避，不刷屏
    }
    setTimeout(tick, delay);
  };
  tick();
}

/* ---------------------------------------------------------------- 登录状态 */

export function setLoginChip(ok, text) {
  const chip = $("#login-chip");
  chip.classList.toggle("ok", !!ok);
  $(".chip-text", chip).textContent = text;
}

/* ---------------------------------------------------------------- 工具 */

export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

export function loadingBlock(text = "载入中…") {
  return `<div class="page-loading"><span class="loading"><i class="spinner"></i>${escapeHtml(text)}</span></div>`;
}

/* ---------------------------------------------------------------- 卡片渲染（复习页/卡片库/搜索共用） */

export function asList(value) {
  if (Array.isArray(value)) return value;
  return value === null || value === undefined || value === "" ? [] : [value];
}

/** 答案正文：要点 / 自测 / 关键词 / 兜底文案；畸形摘要也不会把页面搞崩。 */
export function answerHtml(card) {
  const a = (card || {}).answer || {};
  const parts = [];
  if (a.note) parts.push(`<div class="rv-note">${escapeHtml(a.note)}</div>`);
  const points = asList(a.key_points);
  if (points.length) {
    parts.push(`<ul class="rv-points">${points.map((k) => `<li>${escapeHtml(k)}</li>`).join("")}</ul>`);
  }
  for (const q of asList(a.quiz)) {
    if (!q || typeof q !== "object" || !q.question) continue;
    parts.push(
      `<div class="rv-qa"><div class="rv-qa-q">自测：${escapeHtml(q.question)}</div>` +
        (q.answer ? `<div class="rv-qa-a">${escapeHtml(q.answer)}</div>` : "") +
        "</div>"
    );
  }
  const keywords = asList(a.keywords);
  if (keywords.length) {
    parts.push(`<div class="rv-kw">${keywords.map((k) => `<span class="badge">${escapeHtml(k)}</span>`).join("")}</div>`);
  }
  if (a.fallback) parts.push(`<p class="muted">${escapeHtml(a.fallback)}</p>`);
  return parts.join("") || '<p class="muted">（该卡片暂无内容）</p>';
}

/** 完整卡片弹层：卡片库与搜索页双击/单击都走这里（不影响复习排期）。 */
export async function openCardDetail(bvid, ctx) {
  const box = openModal({
    title: "卡片详情",
    width: 660,
    body: loadingBlock("正在读取卡片…"),
  });
  let d;
  try {
    d = await rpc("card_detail", { bvid });
  } catch (e) {
    box.querySelector(".modal-body").innerHTML = `<div class="muted">读取失败：${escapeHtml(e.message)}</div>`;
    return;
  }
  const state = [
    `状态 ${d.status}`,
    d.due_date ? `到期 ${d.due_date}` : "未排期",
    `已记 ${d.reps} 次`,
    `忘过 ${d.lapses} 次`,
    d.interval_days ? `间隔 ${Number(d.interval_days)} 天` : null,
  ].filter(Boolean);
  const source = {
    subtitle: "由字幕全文精摘",
    intro: "由标题+简介生成（无字幕）",
    title_only: "仅标题占位卡",
  }[d.summary_source];

  box.querySelector(".modal-head h3").textContent = d.title || "卡片详情";
  box.querySelector(".modal-body").innerHTML = `
    <div class="cd-meta">
      <span class="badge">UP：${escapeHtml(d.upper || "未知")}</span>
      <span class="badge">收藏夹：${escapeHtml(d.folder || "—")}</span>
      <span class="badge">${escapeHtml(state.join(" · "))}</span>
      ${source ? `<span class="badge">${escapeHtml(source)}</span>` : ""}
    </div>
    ${d.one_liner ? `<p class="cd-oneliner">${escapeHtml(d.one_liner)}</p>` : ""}
    <div class="cd-answer">${answerHtml(d)}</div>
    ${d.intro ? `<div class="cd-sec"><div class="cd-sec-title">简介</div><p class="muted">${escapeHtml(d.intro.slice(0, 400))}</p></div>` : ""}
    ${
      d.transcript_excerpt
        ? `<div class="cd-sec"><div class="cd-sec-title">字幕节选</div><p class="cd-transcript">${escapeHtml(d.transcript_excerpt)}…</p></div>`
        : d.transcript_note
          ? `<div class="cd-sec"><div class="cd-sec-title">字幕</div><p class="muted">${escapeHtml(d.transcript_note)}</p></div>`
          : ""
    }`;
  const foot = document.createElement("div");
  foot.className = "modal-foot";
  foot.innerHTML = `
    <button class="btn btn-ghost" data-close>关闭</button>
    <span class="grow"></span>
    <button class="btn" data-open-url>🌐 打开原视频</button>
    <button class="btn" data-promote>📅 提前到今天</button>`;
  box.appendChild(foot);
  foot.querySelector("[data-close]").onclick = closeModal;
  foot.querySelector("[data-open-url]").onclick = () =>
    rpc("open_url", { url: `https://www.bilibili.com/video/${bvid}` }).catch((e) => toast(e.message, "warn"));
  foot.querySelector("[data-promote]").onclick = async () => {
    try {
      await rpc("card_promote", { bvid });
      toast("已把这张卡片提前到今天", "success");
      closeModal();
      ctx?.refreshAfterPromote?.();
    } catch (e) {
      toast(e.message, "error");
    }
  };
}
