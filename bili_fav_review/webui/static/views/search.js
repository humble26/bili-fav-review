/* 搜索：FTS5 全文检索（标题 / 简介 / 字幕 / 摘要卡片），点结果看完整卡片。 */

import { $, escapeHtml, loadingBlock, openCardDetail } from "../core.js";

const S = { query: "", searched: false, loading: false, items: [] };

export default {
  key: "search",
  title: "搜索",
  icon: "🔍",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    this.render();
    const input = $("#inp-search", root);
    input.focus();
    if (S.searched) await this.run();
  },

  render() {
    const root = this.root;
    if (!root) return;
    root.innerHTML = `<div class="stack">
      <section class="card card-pad">
        <div class="row">
          <input class="input grow" id="inp-search" placeholder="搜标题 / 简介 / 字幕全文 / 摘要卡片…"
                 value="${escapeHtml(S.query)}" />
          <button class="btn btn-primary" id="btn-search" type="button" ${S.loading ? "disabled" : ""}>
            ${S.loading ? "搜索中…" : "🔍 搜索收藏"}</button>
        </div>
        <div class="hint" style="margin-top:8px">
          中文按子串匹配（3 个字以上走 FTS5 索引，更快）；空结果会自动退回 LIKE 模糊匹配
        </div>
      </section>
      ${this.listHtml()}
    </div>`;
    this.bind();
  },

  listHtml() {
    if (S.loading) return loadingBlock("正在检索…");
    if (!S.searched) {
      return `<div class="empty"><div class="empty-icon">🔍</div>
        <div class="empty-title">输入关键词开始搜索</div>
        <div class="empty-text">例如某个术语、UP 主名字里的一段、字幕里出现过的说法 —— 都能搜到。</div></div>`;
    }
    if (!S.items.length) {
      return `<div class="empty"><div class="empty-icon">🫥</div>
        <div class="empty-title">没有找到包含「${escapeHtml(S.query)}」的收藏</div>
        <div class="empty-text">换个短一点的关键词试试；如果收藏还没同步，先到「我的收藏夹」页同步。</div></div>`;
    }
    return `<section class="card sr">
      <div class="sr-count hint">命中 ${S.items.length} 条</div>
      ${S.items
        .map(
          (r) => `<div class="sr-row" data-bvid="${escapeHtml(r.bvid)}">
            <div class="sr-top">
              <span class="sr-title">${escapeHtml(r.title || "(无标题)")}</span>
              <span class="badge">${escapeHtml(r.upper || "未知 UP")}</span>
              <span class="badge">${escapeHtml(r.folder || "—")}</span>
            </div>
            <div class="sr-snip">${highlight(r.snippet, S.query)}</div>
          </div>`
        )
        .join("")}
    </section>`;
  },

  bind() {
    const root = this.root;
    const input = $("#inp-search", root);
    input.oninput = () => { S.query = input.value; };
    input.onkeydown = (e) => {
      if (e.key === "Enter") this.run();
    };
    $("#btn-search", root).onclick = () => this.run();
    root.querySelectorAll(".sr-row").forEach((row) => {
      row.onclick = () => openCardDetail(row.dataset.bvid, this.ctx);
    });
  },

  async run() {
    const q = (S.query || "").trim();
    if (!q) return;
    S.query = q;
    S.loading = true;
    this.render();
    try {
      const d = await this.ctx.rpc("search", { query: q, limit: 30 });
      S.items = d.items || [];
    } catch (e) {
      this.ctx.toast(`搜索失败：${e.message}`, "error");
      S.items = [];
    }
    S.searched = true;
    S.loading = false;
    this.render();
    this.root && $("#inp-search", this.root)?.focus();
  },

  async refresh() {
    await this.run();
  },
};

/** 命中片段里的 «…» 高亮成 <mark>（服务端 snippet 用 «» 标出命中位置）。 */
function highlight(text, query) {
  let html = escapeHtml(text || "");
  html = html.replace(/«/g, '<mark>').replace(/»/g, "</mark>");
  if (html.includes("<mark>")) return html;
  const q = escapeHtml(query || "");
  if (!q) return html;
  return html.split(q).join(`<mark>${q}</mark>`);
}
