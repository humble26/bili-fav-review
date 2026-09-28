/* 复习页：新卡直接读内容自评；复习卡先回忆 → 显示答案 → 三色评分。
   快捷键：空格/回车 显示答案 · 1/2/3 评分 · S 跳过 */

import { $, answerHtml, escapeHtml, loadingBlock } from "../core.js";

const S = {
  loading: true,
  cards: [],
  idx: 0,
  revealed: false,
  undoAvailable: false,
  done: false,
  remaining: 0,
  nextDue: null,
  empty: null,
  limit: 30,
  busy: false,
};

export default {
  key: "review",
  title: "今日复习",
  icon: "🧠",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    if (S.loading) {
      await this.load();
      return;
    }
    this.render();
  },

  async refresh() {
    this.render();
  },

  async load() {
    S.loading = true;
    this.render();
    const d = await this.ctx.rpc("review_start");
    S.loading = false;
    S.cards = d.cards || [];
    S.limit = d.session_limit || 30;
    S.idx = 0;
    S.revealed = false;
    S.undoAvailable = false;
    S.done = false;
    S.empty = S.cards.length
      ? null
      : { nextDue: d.next_due, promotable: d.promotable, totalVideos: d.total_videos };
    this.render();
  },

  /* ------------------------------------------------------------ 渲染 */

  render() {
    const root = this.root;
    if (!root) return;
    if (S.loading) {
      root.innerHTML = loadingBlock("正在准备今天的卡片…");
      return;
    }
    if (!S.cards.length) return this.renderEmpty(root);
    if (S.done) return this.renderDone(root);

    const card = S.cards[S.idx];
    const total = S.cards.length;
    const pct = Math.round((S.idx / total) * 100);
    // 新卡首次学习：没有可回忆的旧记忆，直接展示内容，读完自评
    S.revealed = !!card.is_new;
    const progress = card.is_new
      ? `🆕 新卡 ${S.idx + 1}/${total}（首次学习）`
      : `第 ${S.idx + 1}/${total} 张 · 记过 ${card.reps} 次 · 忘过 ${card.lapses} 次`;

    root.innerHTML = `
      <div class="rv">
        <div class="rv-top">
          <div class="rv-progress-text">${escapeHtml(progress)}</div>
          <div class="rv-keys">
            <span><kbd>空格</kbd>显示答案</span>
            <span><kbd>1</kbd><kbd>2</kbd><kbd>3</kbd>评分</span>
            <span><kbd>S</kbd>跳过</span>
          </div>
        </div>
        <div class="rv-bar"><i style="width:${pct}%"></i></div>

        <section class="card rv-card">
          <div class="rv-meta">
            <span class="badge">UP：${escapeHtml(card.upper || "未知")}</span>
            <span class="badge">收藏夹：${escapeHtml(card.folder || "—")}</span>
            ${card.is_new ? '<span class="badge">首次学习</span>' : ""}
          </div>
          <h2 class="rv-title">${escapeHtml(card.title)}</h2>
          <p class="rv-oneliner">${escapeHtml(card.one_liner || "（暂无摘要，凭标题回忆）")}</p>
          ${card.quiz_question ? `<div class="rv-quiz">自测：${escapeHtml(card.quiz_question)}</div>` : ""}
        </section>

        <div class="rv-actions">
          <button class="btn" id="btn-reveal" type="button">👁 显示答案</button>
          <button class="btn" id="btn-video" type="button">🌐 重看视频</button>
        </div>

        <section class="card rv-answer">
          <div class="rv-answer-head">
            <span>答案</span>
            ${card.is_new ? '<span class="badge">通读后凭感觉评估能记多久</span>' : ""}
          </div>
          <div class="rv-answer-body" id="rv-answer"></div>
        </section>

        <div class="rv-footer">
          <button class="btn btn-ghost" id="btn-skip" type="button">跳过这张<kbd>S</kbd></button>
          <button class="btn btn-ghost" id="btn-undo" type="button" disabled>↩ 撤销</button>
          <div class="rv-grades">
            <button class="btn btn-danger" data-grade="0" type="button">😅 忘了<kbd>1</kbd></button>
            <button class="btn btn-warn" data-grade="1" type="button">🤔 模糊<kbd>2</kbd></button>
            <button class="btn btn-ok" data-grade="2" type="button">😄 记得<kbd>3</kbd></button>
          </div>
        </div>
      </div>`;

    this.writeAnswer(card, false);
    this.syncButtons();
    this.bind();
  },

  renderEmpty(root) {
    const e = S.empty || {};
    const hint = e.nextDue
      ? `下一批到期：${e.nextDue}`
      : e.totalVideos
        ? "暂无安排。可以到「我的收藏夹」页同步新收藏，或点下面的按钮把未来新卡提前到今天。"
        : "收藏库还是空的：先去「我的收藏夹」页拉取并同步收藏夹（需要先登录），也可以先跑一次 bili-review demo 塞 4 张演示卡体验全流程。";
    root.innerHTML = `<div class="stack"><div class="empty">
      <div class="empty-icon">🎉</div>
      <div class="empty-title">今天没有到期卡片</div>
      <div class="empty-text">${escapeHtml(hint)}</div>
      ${
        e.promotable > 0
          ? `<button class="btn btn-primary" id="btn-promote" type="button">
               📅 有 ${e.promotable} 张新卡排在之后 —— 点此提前到今天学习</button>`
          : ""
      }
    </div></div>`;
    const promote = $("#btn-promote", root);
    if (promote) promote.onclick = () => this.promote();
  },

  renderDone(root) {
    const sub = S.remaining
      ? `今日还剩 ${S.remaining} 张到期`
      : "今天的卡片全部清空 🎉";
    root.innerHTML = `<div class="stack"><section class="card rv-done">
      <div class="big">🎉</div>
      <h2>本轮复习完成</h2>
      <p class="sub">${escapeHtml(sub)}${!S.remaining && S.nextDue ? `　下一批到期：${S.nextDue}` : ""}</p>
      <div class="rv-done-actions">
        ${S.remaining ? '<button class="btn btn-primary" id="btn-again" type="button">继续复习剩余</button>' : ""}
        <button class="btn" id="btn-home" type="button">返回首页</button>
      </div>
    </section></div>`;
    const again = $("#btn-again", root);
    if (again) again.onclick = () => this.load();
    $("#btn-home", root).onclick = () => this.ctx.show("home");
  },

  /* ------------------------------------------------------------ 交互 */

  writeAnswer(card, animate) {
    const host = $("#rv-answer", this.root);
    if (!host) return;
    if (!S.revealed) {
      host.innerHTML =
        '<div class="rv-answer-empty">先在脑中回忆这期视频讲了什么，再点「显示答案」</div>';
      return;
    }
    host.innerHTML = answerHtml(card);
    if (animate) host.classList.add("rv-reveal-anim");
  },

  syncButtons() {
    const card = S.cards[S.idx];
    const reveal = $("#btn-reveal", this.root);
    if (reveal) reveal.disabled = S.revealed || card.is_new;
    this.root.querySelectorAll("[data-grade]").forEach((b) => (b.disabled = !S.revealed));
    const undo = $("#btn-undo", this.root);
    if (undo) undo.disabled = !S.undoAvailable;
  },

  bind() {
    const root = this.root;
    $("#btn-reveal", root).onclick = () => this.reveal(true);
    $("#btn-video", root).onclick = () => this.openVideo();
    $("#btn-skip", root).onclick = () => this.skip();
    $("#btn-undo", root).onclick = () => this.undo();
    root.querySelectorAll("[data-grade]").forEach((b) => {
      b.onclick = () => this.grade(Number(b.dataset.grade));
    });
  },

  onKey(e) {
    if (S.loading || S.done || !S.cards.length) return;
    const key = (e.key || "").toLowerCase();
    if (key === " " || key === "enter") {
      e.preventDefault();
      this.reveal(true);
    } else if (key === "1" && S.revealed) this.grade(0);
    else if (key === "2" && S.revealed) this.grade(1);
    else if (key === "3" && S.revealed) this.grade(2);
    else if (key === "s") this.skip();
  },

  reveal(animate = true) {
    if (S.revealed || S.done || !S.cards.length || S.loading) return;
    S.revealed = true;
    this.writeAnswer(S.cards[S.idx], animate);
    this.syncButtons();
  },

  openVideo() {
    const card = S.cards[S.idx];
    if (card?.url) {
      this.ctx.rpc("open_url", { url: card.url }).catch((e) => this.ctx.toast(e.message, "warn"));
    }
  },

  async grade(grade) {
    if (!S.revealed || S.done || !S.cards.length || S.busy) return;
    S.busy = true;
    const card = S.cards[S.idx];
    try {
      const r = await this.ctx.rpc("review_grade", {
        bvid: card.bvid,
        grade,
        title: card.title,
      });
      S.undoAvailable = true;
      S.remaining = r.remaining;
      this.advance();
    } catch (e) {
      this.ctx.toast(`评分失败：${e.message}`, "error");
    } finally {
      S.busy = false;
    }
  },

  async undo() {
    if (!S.undoAvailable) return;
    try {
      const r = await this.ctx.rpc("review_undo");
      if (!r.ok) {
        this.ctx.toast("没有可撤销的评分", "warn");
        return;
      }
      const i = S.cards.findIndex((c) => c.bvid === r.bvid);
      if (i >= 0) {
        S.idx = i;
        S.revealed = false;
      }
      S.undoAvailable = false;
      S.done = false;
      this.render();
    } catch (e) {
      this.ctx.toast(`撤销失败：${e.message}`, "error");
    }
  },

  skip() {
    if (S.loading || S.done || !S.cards.length) return;
    // 日志统一走服务端出口（同时写 gui.log 与面板），本地再打印会重复一行
    this.ctx.rpc("note", { level: "info", text: "已跳过一张（不计入复习）" }).catch(() => {});
    this.advance();
  },

  advance() {
    S.idx += 1;
    S.revealed = false;
    if (S.idx >= S.cards.length) {
      this.finish();
      return;
    }
    this.render();
  },

  async finish() {
    S.done = true;
    try {
      const s = await this.ctx.rpc("review_summary");
      S.remaining = s.remaining;
      S.nextDue = s.next_due;
    } catch {
      /* 汇总失败不影响「完成」这一事实 */
    }
    this.render();
  },

  async promote() {
    try {
      const r = await this.ctx.rpc("review_promote");
      this.ctx.toast(`已把 ${r.moved} 张新卡提前到今天`, "success");
      await this.load();
    } catch (e) {
      this.ctx.toast(e.message, "error");
    }
  },
};
