import { $, escapeHtml } from "../core.js";

export default {
  key: "home",
  title: "首页",
  icon: "🏠",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    const d = await ctx.rpc("home");
    const steps = ctx.state.boot?.guide_steps || [];
    const c = d.counts;
    const due = d.due;
    const dueLine = due.total
      ? `今日到期 <b>${due.total}</b> 张 —— <span class="hl-new">🆕 新卡 ${due.new}</span> · <span class="hl-rev">复习 ${due.old}</span>`
      : escapeHtml(
          `今天没有到期卡片，休息一下 🎉` +
            (d.next_due ? `　下一批到期：${d.next_due}` : "") +
            (d.promotable ? `　另有 ${d.promotable} 张新卡排在之后` : "")
        );
    const btnLabel = due.total ? "▶&nbsp; 开始复习" : "▶&nbsp; 今天没有到期卡片";

    root.innerHTML = `
      <div class="stack">
        <section class="card hero">
          <div>
            <h2>今天该复习了</h2>
            <p class="hero-sub">${dueLine}</p>
          </div>
          <button class="btn btn-primary btn-lg" id="btn-start-review" type="button">
            ${btnLabel}${due.total ? `（${due.total} 张）` : ""}
          </button>
        </section>

        <section class="tiles">
          ${tile("var(--info)", c.total, "收藏视频")}
          ${tile("var(--ok)", c.with_transcript, "已有字幕")}
          ${tile("var(--warn)", c.with_summary, "已生成卡片")}
          ${tile("var(--purple)", c.mature, "长期记忆")}
        </section>

        <section class="card card-pad">
          <div class="card-head">
            <h3>第一次使用？照这四步走</h3>
            <span class="sub">点右上角「使用指南」看完整说明</span>
          </div>
          <div class="steps">
            ${steps
              .map(
                (s, i) => `<div class="step">
                  <div class="step-no">${i + 1}</div>
                  <div>
                    <div class="step-title">${escapeHtml(s.title)}</div>
                    <div class="step-text">${escapeHtml(s.text)}</div>
                  </div></div>`
              )
              .join("")}
          </div>
        </section>
      </div>`;

    $("#btn-start-review", root).onclick = () => ctx.show("review");
  },

  async refresh() {
    await this.mount(this.root, this.ctx);
  },
};

function tile(color, value, label) {
  return `<div class="card tile">
    <i class="tile-dot" style="color:${color}">●</i>
    <div class="tile-num">${Number(value || 0)}</div>
    <div class="tile-label">${escapeHtml(label)}</div>
  </div>`;
}
