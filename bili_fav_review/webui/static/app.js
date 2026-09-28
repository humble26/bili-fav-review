/* 界面外壳：路由、侧栏、顶栏、日志面板挂载、扫码登录与帮助弹层。 */

import cardsView from "./views/cards.js";
import foldersView from "./views/folders.js";
import homeView from "./views/home.js";
import reviewView from "./views/review.js";
import searchView from "./views/search.js";
import settingsView from "./views/settings.js";
import statsView from "./views/stats.js";
import {
  $, appendLog, clearLog, closeModal, escapeHtml, loadingBlock, onEvent, openModal,
  rpc, setLoginChip, startPolling, state, toast,
} from "./core.js";

const BASE_FONT =
  '"HarmonyOS Sans SC","MiSans","MiSans Normal","Source Han Sans SC","思源黑体 CN",' +
  '"Noto Sans SC","Noto Sans CJK SC","DengXian","等线","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif';

/* ---------------------------------------------------------------- 页面注册 */

const VIEWS = [
  homeView,
  foldersView,
  reviewView,
  cardsView,
  searchView,
  statsView,
  settingsView,
];

const ctx = { rpc, toast, appendLog, show, openModal, closeModal, state };

/* ---------------------------------------------------------------- 路由 */

function buildNav() {
  $("#nav").innerHTML = VIEWS.map(
    (v) => `<button class="nav-item" data-view="${v.key}" type="button">
      <span class="nav-icon">${v.icon}</span><span>${v.title}</span></button>`
  ).join("");
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.onclick = () => show(btn.dataset.view);
  });
}

export function show(key) {
  const view = VIEWS.find((v) => v.key === key) || VIEWS[0];
  state.view = view;
  if (location.hash.slice(2) !== view.key) {
    try { history.replaceState(null, "", `#/${view.key}`); } catch { /* 忽略 */ }
  }
  $("#page-title").textContent = view.title;
  document.querySelectorAll(".nav-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === view.key)
  );
  const root = $("#view-root");
  root.innerHTML = loadingBlock();
  root.scrollTop = 0;
  Promise.resolve(view.mount(root, ctx)).catch((e) => {
    root.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>
      <div class="empty-title">这一页加载失败</div>
      <div class="empty-text">${escapeHtml(e.message)}</div></div>`;
    toast(`加载失败：${e.message}`, "error");
  });
}

async function refreshView() {
  const view = state.view;
  if (!view) return;
  try {
    if (view.refresh) await view.refresh();
    else await view.mount($("#view-root"), ctx);
  } catch (e) {
    toast(`刷新失败：${e.message}`, "error");
  }
}

/* ---------------------------------------------------------------- 扫码登录 */

let qrUnsubs = [];

function unsubQr() {
  qrUnsubs.forEach((fn) => fn());
  qrUnsubs = [];
}

function qrSvg(matrix) {
  const n = matrix.length;
  const cells = [];
  for (let y = 0; y < n; y += 1) {
    const row = matrix[y];
    let x = 0;
    while (x < n) {
      if (row[x] === "1") {
        let w = 1;
        while (x + w < n && row[x + w] === "1") w += 1;
        cells.push(`<rect x="${x}" y="${y}" width="${w}" height="1"/>`);
        x += w;
      } else x += 1;
    }
  }
  return `<svg class="qr-svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img" aria-label="登录二维码">
    <rect width="${n}" height="${n}" fill="#fff"/><g fill="#14161c">${cells.join("")}</g></svg>`;
}

function openLogin() {
  unsubQr();
  let closed = false;
  openModal({
    title: "扫码登录 B 站",
    width: 420,
    body: `<div class="qr-wrap">
        <div class="qr-box" id="qr-box"><span class="loading"><i class="spinner"></i>正在获取二维码…</span></div>
        <div class="qr-status" id="qr-status">正在获取二维码…</div>
        <p class="hint">打开手机 B 站 App → 右上角「扫一扫」→ 扫描并确认登录</p>
      </div>`,
    actions: [{ label: "取消", onClick: () => { rpc("login_cancel"); closeModal(); } }],
    onClose: () => { closed = true; rpc("login_cancel"); unsubQr(); },
  });
  const setStatus = (text) => { const el = $("#qr-status"); if (el) el.textContent = text; };
  const start = (retry) => {
    rpc("login_start")
      .then((r) => {
        if (r.started || closed) return;
        // 上一次扫码还在轮询收尾（取消最长需 2 秒被感知），稍后自动再试一次
        setStatus("上一次扫码还在收尾，正在重试…");
        if (!retry) {
          setTimeout(() => { if (!closed) start(true); }, 2500);
        } else {
          setStatus("请稍候再点一次「扫码登录」");
        }
      })
      .catch((e) => setStatus(`启动失败：${e.message}`));
  };
  qrUnsubs.push(onEvent("qr", (d) => {
    const box = $("#qr-box");
    if (box) box.innerHTML = qrSvg(d.matrix);
    setStatus("等待扫码…");
  }));
  qrUnsubs.push(onEvent("login_status", (d) => setStatus(d.text)));
  qrUnsubs.push(onEvent("login_failed", (d) => setStatus(`登录失败：${d.error}`)));
  start(false);
}

/* ---------------------------------------------------------------- 帮助 */

async function openHelp() {
  let text = "正在载入…";
  try { text = (await rpc("content")).help; } catch { /* 保留兜底文案 */ }
  openModal({
    title: "使用指南（速览版）",
    width: 620,
    body: `<pre class="help-pre">${escapeHtml(text)}</pre>`,
    actions: [
      { label: "打开完整指南", onClick: async () => {
          const r = await rpc("open_path", { kind: "guide" });
          if (!r.ok) toast(r.error, "warn");
        } },
      { label: "打开数据文件夹", onClick: () => rpc("open_path", { kind: "data" }) },
      { label: "知道了", kind: "btn-primary", onClick: () => closeModal() },
    ],
  });
}

/* ---------------------------------------------------------------- 字体（数据目录自定义） */

async function applyFonts() {
  try {
    const { files } = await rpc("fonts");
    if (!files.length) return;
    const style = document.createElement("style");
    style.textContent = files
      .map((f, i) => `@font-face{font-family:"bfr-user-${i}";src:url("${f.url}");font-display:swap;}`)
      .join("");
    document.head.appendChild(style);
    const families = files.map((_, i) => `"bfr-user-${i}"`).join(",");
    document.documentElement.style.setProperty("--font-family", `${families},${BASE_FONT}`);
    appendLog("info", `已加载数据目录自定义字体：${files.map((f) => f.name).join("、")}`);
  } catch { /* 字体属于增强项，失败不影响使用 */ }
}

/* ---------------------------------------------------------------- 启动 */

function bindShell() {
  onEvent("login_state", (d) => setLoginChip(d.ok, d.text));
  // 登录成功是全局事件：即使弹层已被关掉（例如关窗瞬间扫完码），状态也要更新
  onEvent("login_success", (d) => {
    closeModal();
    setLoginChip(true, `已登录 · UID ${d.uid}`);
    toast(`登录成功，欢迎 UID ${d.uid}`, "success");
    appendLog("success", `登录成功：UID ${d.uid}`);
    rpc("check_login");
    refreshView();
  });
  $("#btn-login").onclick = openLogin;
  $("#btn-help").onclick = openHelp;
  $("#btn-refresh").onclick = async () => {
    await refreshView();
    rpc("check_login");
    toast("已刷新", "info", 1500);
  };
  $("#btn-clear-log").onclick = clearLog;

  // 日志面板可折叠（状态记在 localStorage；复习时能腾出屏幕高度）
  const logPanel = $("#log-panel");
  try {
    if (localStorage.getItem("bfr.log.collapsed") === "1") logPanel.classList.add("collapsed");
  } catch { /* localStorage 不可用时用默认展开 */ }
  $("#btn-toggle-log").onclick = () => {
    const collapsed = logPanel.classList.toggle("collapsed");
    try { localStorage.setItem("bfr.log.collapsed", collapsed ? "1" : "0"); } catch { /* 忽略 */ }
  };
  $("#modal-root").addEventListener("click", (e) => {
    if (e.target.id === "modal-root") closeModal();
  });
  // hash 深链：冷启动与运行中改哈希都能切页（show 用 replaceState，不会触发回环）
  window.addEventListener("hashchange", () => {
    const key = location.hash.slice(2);
    if (key && key !== state.view?.key) show(key);
  });
  document.addEventListener("keydown", (e) => {
    const modalOpen = !$("#modal-root").classList.contains("hidden");
    if (e.key === "Escape") {
      if (modalOpen) closeModal();
      return;
    }
    if (modalOpen) return; // 弹层打开时不吃页面快捷键（否则会在背后误评分/误跳过）
    if (e.target.closest?.("input, textarea, select")) return;
    state.view?.onKey?.(e);
  });
}

async function boot() {
  bindShell();
  buildNav();
  try {
    state.boot = await rpc("bootstrap");
    $("#app-version").textContent = `v${state.boot.version}`;
    applyFonts();
  } catch (e) {
    toast(`初始化失败：${e.message}`, "error", 6000);
  }
  show(location.hash.slice(2) || "home");
  rpc("check_login");
  startPolling();
}

boot();
