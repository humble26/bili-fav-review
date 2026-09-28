/* 我的收藏夹：拉取列表 → 勾选 → 一键增量同步（拉字幕 → 生成卡片）。
   同步进度全部走运行日志（服务端 ui.* 输出），这里只负责勾选与状态。 */

import { $, escapeHtml, loadingBlock, onEvent } from "../core.js";

const S = {
  fetched: false,
  loading: false,
  items: null, // null=还没拉过；[]=拉到了但没有夹子
  selected: new Set(),
  user: "",
  error: null,
  foldersBusy: false,
  syncRunning: false,
  withLlm: true,
  limit: "",
};

let unsub = [];

export default {
  key: "folders",
  title: "我的收藏夹",
  icon: "📂",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    unsub.forEach((fn) => fn());
    unsub = [];
    unsub.push(
      onEvent("folders", (d) => {
        S.items = d.items || [];
        S.user = d.user || "";
        S.error = null;
        S.loading = false;
        S.foldersBusy = false;
        S.fetched = true;
        S.selected = new Set(S.items.filter((f) => f.selected).map((f) => f.id));
        this.render();
      })
    );
    unsub.push(
      onEvent("folders_error", (d) => {
        S.error = d.error || "拉取失败";
        S.loading = false;
        S.foldersBusy = false;
        this.render();
      })
    );
    unsub.push(
      onEvent("sync_state", (d) => {
        S.syncRunning = !!d.running;
        this.render();
        if (!d.running) {
          if (d.ok) ctx.toast("同步完成 ✔ 可以去「今日复习」看看新卡片", "success", 4200);
          else ctx.toast("同步未完成，请看下方运行日志", "error", 4800);
        }
      })
    );
    try {
      const j = await ctx.rpc("jobs");
      S.foldersBusy = !!j.folders;
      S.syncRunning = !!j.sync;
    } catch {
      /* 状态拿不到就按空闲处理 */
    }
    this.render();
  },

  render() {
    const root = this.root;
    if (!root) return;
    const items = S.items || [];
    const picked = items.filter((f) => S.selected.has(f.id));
    const busy = S.loading || S.foldersBusy || S.syncRunning;

    const toolbar = `
      <section class="card card-pad">
        <div class="row">
          <button class="btn" id="btn-fetch" type="button" ${S.loading || S.foldersBusy ? "disabled" : ""}>
            ${S.loading || S.foldersBusy ? "正在拉取…" : "↻ 拉取收藏夹列表"}</button>
          <button class="btn btn-ghost btn-sm" id="btn-all" type="button" ${items.length ? "" : "disabled"}>全选</button>
          <button class="btn btn-ghost btn-sm" id="btn-none" type="button" ${items.length ? "" : "disabled"}>清空勾选</button>
          <span class="grow"></span>
          <label class="check"><input type="checkbox" id="chk-llm" ${S.withLlm ? "checked" : ""} ${
            S.syncRunning ? "disabled" : ""
          } /> 生成 AI 复习卡片（需要 API Key）</label>
          <span class="hint">本次最多</span>
          <input class="input input-xs" id="inp-limit" value="${escapeHtml(S.limit)}" placeholder="不限" ${
            S.syncRunning ? "disabled" : ""
          } />
          <span class="hint">个</span>
        </div>
        <div class="row" style="margin-top:10px; justify-content: space-between">
          <span class="hint">点击整行即可勾选/取消 · 同步是增量的，重复执行无副作用 · 失效视频自动跳过</span>
          <button class="btn btn-primary" id="btn-sync" type="button" ${
            picked.length && !busy ? "" : "disabled"
          }>▶ 开始同步${picked.length ? `（${picked.length} 个夹子）` : ""}</button>
        </div>
        ${S.syncRunning ? '<div class="banner info"><i class="spinner"></i>同步进行中：进度在下方运行日志实时输出，中途别关窗口</div>' : ""}
      </section>`;

    root.innerHTML = `<div class="stack">
      ${toolbar}
      ${this.listHtml()}
    </div>`;
    this.bind();
  },

  listHtml() {
    if (S.loading || (S.foldersBusy && !S.items)) return loadingBlock("正在拉取收藏夹列表…");
    if (S.error) {
      return `<div class="empty">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">拉取收藏夹失败</div>
        <div class="empty-text">${escapeHtml(S.error)}</div>
        <div class="hint">排查：提示登录相关 → 点右上角「扫码登录」重新登录；提示风控/请求频繁 → 等几分钟再试；其他 → 检查网络或代理</div>
      </div>`;
    }
    if (!S.fetched) {
      return `<div class="empty">
        <div class="empty-icon">📂</div>
        <div class="empty-title">先点「拉取收藏夹列表」</div>
        <div class="empty-text">会用你登录的账号读取收藏夹（只读，不改动 B 站上的任何数据），然后勾选要复习的夹子开始同步。</div>
      </div>`;
    }
    if (!S.items.length) {
      return `<div class="empty"><div class="empty-icon">🗂</div>
        <div class="empty-title">这个账号还没有收藏夹</div>
        <div class="empty-text">先去 B 站创建收藏夹并收藏几个视频，再回来拉取。</div></div>`;
    }
    return `<section class="card ft-list">
      <div class="ft-head">
        <span class="ft-check"></span><span>收藏夹</span><span class="ft-num">视频数</span><span class="ft-id">ID</span>
      </div>
      ${S.items
        .map(
          (f) => `<div class="ft-row ${S.selected.has(f.id) ? "on" : ""}" data-id="${f.id}">
            <span class="ft-check">${S.selected.has(f.id) ? "✓" : ""}</span>
            <span class="ft-title">${escapeHtml(f.title || "(未命名)")}</span>
            <span class="ft-num">${Number(f.count || 0)}</span>
            <span class="ft-id">${f.id}</span>
          </div>`
        )
        .join("")}
      <div class="ft-foot hint">${
        S.user ? `账号 ${escapeHtml(S.user)} · ` : ""
      }已勾选 ${S.selected.size} / ${S.items.length} 个收藏夹</div>
    </section>`;
  },

  bind() {
    const root = this.root;
    const fetchBtn = $("#btn-fetch", root);
    if (fetchBtn) fetchBtn.onclick = () => this.fetch();
    const all = $("#btn-all", root);
    if (all) all.onclick = () => { S.selected = new Set(S.items.map((f) => f.id)); this.render(); };
    const none = $("#btn-none", root);
    if (none) none.onclick = () => { S.selected = new Set(); this.render(); };
    const llm = $("#chk-llm", root);
    if (llm) llm.onchange = () => { S.withLlm = llm.checked; };
    const limit = $("#inp-limit", root);
    if (limit) limit.oninput = () => { S.limit = limit.value.replace(/[^\d]/g, ""); };
    const sync = $("#btn-sync", root);
    if (sync) sync.onclick = () => this.sync();
    root.querySelectorAll(".ft-row").forEach((row) => {
      row.onclick = () => {
        const id = Number(row.dataset.id);
        if (S.selected.has(id)) S.selected.delete(id);
        else S.selected.add(id);
        this.render();
      };
    });
  },

  async fetch() {
    S.loading = true;
    S.error = null;
    this.render();
    try {
      const r = await this.ctx.rpc("folders");
      if (!r.started) {
        S.loading = false;
        S.foldersBusy = true;
        this.render();
      }
      // 结果通过 folders / folders_error 事件回来
    } catch (e) {
      S.loading = false;
      S.error = e.message;
      this.render();
    }
  },

  async sync() {
    const ids = [...S.selected];
    if (!ids.length) return;
    try {
      const r = await this.ctx.rpc("sync_start", {
        folders: ids,
        limit: S.limit,
        with_llm: S.withLlm,
      });
      if (!r.started) {
        this.ctx.toast(r.error || "同步没能启动", "warn");
        return;
      }
      S.syncRunning = true;
      this.render();
    } catch (e) {
      this.ctx.toast(e.message, "error");
    }
  },
};
