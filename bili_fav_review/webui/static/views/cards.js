/* 卡片库：全量卡片的书架 —— 状态筛选 / 详情 / 补齐摘要 / 导出 Anki。 */

import { $, escapeHtml, loadingBlock, onEvent, openCardDetail } from "../core.js";

const FILTERS = ["全部", "新卡", "今日到期", "已逾期", "长期记忆", "复习中"];
const BADGE = {
  新卡: "🆕 新卡",
  今日到期: "🔥 今日到期",
  已逾期: "⚠ 已逾期",
  长期记忆: "🌳 长期记忆",
  复习中: "🔁 复习中",
};

const S = {
  loading: true,
  flt: "全部",
  items: [],
  counts: {},
  shown: 0,
  capped: false,
  fillBusy: false,
  ankiBusy: false,
  exportDir: "",
};

let unsub = [];

export default {
  key: "cards",
  title: "卡片库",
  icon: "🗂",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    unsub.forEach((fn) => fn());
    unsub = [];
    unsub.push(
      onEvent("fill_state", (d) => {
        S.fillBusy = !!d.running;
        this.render();
        if (!d.running) this.load();
      })
    );
    unsub.push(
      onEvent("anki_state", (d) => {
        S.ankiBusy = !!d.running;
        if (!d.running) {
          S.exportDir = d.ok ? d.dir || "" : "";
          if (d.ok) ctx.toast("Anki 牌组已导出，可在下方打开文件夹", "success", 5000);
          else ctx.toast("导出失败，请看下方运行日志", "error", 4800);
        }
        this.render();
      })
    );
    try {
      const j = await ctx.rpc("jobs");
      S.fillBusy = !!j.fill;
      S.ankiBusy = !!j.anki;
    } catch {
      /* 拿不到就按空闲处理 */
    }
    await this.load();
  },

  async load() {
    S.loading = true;
    this.render();
    try {
      const d = await this.ctx.rpc("cards", { flt: S.flt });
      S.items = d.items || [];
      S.counts = d.counts || {};
      S.shown = d.shown || 0;
      S.capped = !!d.capped;
    } catch (e) {
      this.ctx.toast(`读取卡片失败：${e.message}`, "error");
      S.items = [];
    }
    S.loading = false;
    this.render();
  },

  render() {
    const root = this.root;
    if (!root) return;
    root.innerHTML = `<div class="stack">
      <section class="card card-pad">
        <div class="row">
          <button class="btn btn-sm" id="btn-reload" type="button">↻ 刷新</button>
          <button class="btn btn-sm" id="btn-fill" type="button" ${S.fillBusy ? "disabled" : ""}>
            ${S.fillBusy ? "正在补齐…" : "🤖 补齐缺失摘要"}</button>
          <button class="btn btn-sm" id="btn-anki" type="button" ${S.ankiBusy ? "disabled" : ""}>
            ${S.ankiBusy ? "正在导出…" : "📤 导出 Anki"}</button>
          <span class="grow"></span>
          <span class="hint">共 ${S.counts["全部"] || 0} 张 · 当前 ${S.shown} 张</span>
        </div>
        <div class="row chips" style="margin-top:10px">
          ${FILTERS.map(
            (f) => `<button class="chip-btn ${S.flt === f ? "on" : ""}" data-flt="${f}" type="button">
              ${escapeHtml(f)}<b>${S.counts[f] || 0}</b></button>`
          ).join("")}
        </div>
        ${S.exportDir ? `<div class="banner ok">已导出 Anki 牌组到 <span class="kv">${escapeHtml(S.exportDir)}</span>
          <button class="btn btn-xs" id="btn-open-exports" type="button">打开文件夹</button></div>` : ""}
        ${
          S.fillBusy || S.ankiBusy
            ? `<div class="banner info"><i class="spinner"></i>${S.fillBusy ? "正在补齐摘要" : "正在导出"}，进度见下方运行日志</div>`
            : ""
        }
        <div class="hint" style="margin-top:8px">单击任意卡片看完整内容（要点 / 自测 / 字幕节选），不改动复习排期 · 「补齐摘要」会调用 AI（需要 API Key）</div>
      </section>
      ${this.listHtml()}
    </div>`;
    this.bind();
  },

  listHtml() {
    if (S.loading) return loadingBlock("正在读取卡片…");
    if (!S.items.length) {
      const none = !(S.counts["全部"] || 0);
      return `<div class="empty"><div class="empty-icon">${none ? "🗂" : "🔍"}</div>
        <div class="empty-title">${none ? "卡片库还是空的" : "这个筛选下没有卡片"}</div>
        <div class="empty-text">${
          none
            ? "先到「我的收藏夹」页同步一批收藏，卡片会自动生成。"
            : "换个筛选看看，或点「全部」查看所有卡片。"
        }</div></div>`;
    }
    return `<section class="card tb">
      <div class="tb-head">
        <span class="tb-status">状态</span><span class="tb-title">标题</span>
        <span class="tb-up">UP主</span><span class="tb-folder">收藏夹</span>
        <span class="tb-due">到期日</span><span class="tb-int">间隔</span>
      </div>
      ${S.items
        .map(
          (c) => `<div class="tb-row" data-bvid="${escapeHtml(c.bvid)}" title="${escapeHtml(c.title)}">
            <span class="tb-status"><i class="dot ${statusClass(c.status)}"></i>${escapeHtml(BADGE[c.status] || c.status)}</span>
            <span class="tb-title">${escapeHtml(c.title || "(无标题)")}${
              c.has_summary ? "" : ' <span class="badge">无摘要</span>'
            }</span>
            <span class="tb-up">${escapeHtml(c.upper || "—")}</span>
            <span class="tb-folder">${escapeHtml(c.folder || "—")}</span>
            <span class="tb-due">${escapeHtml(c.due || "—")}</span>
            <span class="tb-int">${c.interval === null || c.interval === undefined ? "—" : Number(c.interval)}</span>
          </div>`
        )
        .join("")}
      ${S.capped ? '<div class="tb-foot hint">卡片太多，只显示前 1000 张；用「搜索」页或筛选来定位具体卡片</div>' : ""}
    </section>`;
  },

  bind() {
    const root = this.root;
    $("#btn-reload", root).onclick = () => this.load();
    $("#btn-fill", root).onclick = () => this.fill();
    $("#btn-anki", root).onclick = () => this.anki();
    const open = $("#btn-open-exports", root);
    if (open) open.onclick = () => this.ctx.rpc("open_path", { kind: "exports" }).catch(() => {});
    root.querySelectorAll("[data-flt]").forEach((btn) => {
      btn.onclick = () => {
        S.flt = btn.dataset.flt;
        this.load();
      };
    });
    root.querySelectorAll(".tb-row").forEach((row) => {
      row.onclick = () =>
        openCardDetail(row.dataset.bvid, { ...this.ctx, refreshAfterPromote: () => this.load() });
    });
  },

  async fill() {
    try {
      const r = await this.ctx.rpc("fill_start", { limit: 100 });
      if (!r.started) {
        this.ctx.toast(r.error || "补齐没能启动", "warn");
        return;
      }
      S.fillBusy = true;
      this.render();
    } catch (e) {
      this.ctx.toast(e.message, "error");
    }
  },

  async anki() {
    try {
      const r = await this.ctx.rpc("anki_start");
      if (!r.started) {
        this.ctx.toast(r.error || "导出没能启动", "warn");
        return;
      }
      S.ankiBusy = true;
      this.render();
    } catch (e) {
      this.ctx.toast(e.message, "error");
    }
  },

  async refresh() {
    await this.load();
  },
};

function statusClass(status) {
  return { 新卡: "b-new", 今日到期: "b-warn", 已逾期: "b-danger", 长期记忆: "b-ok", 复习中: "b-info" }[status] || "b-info";
}
