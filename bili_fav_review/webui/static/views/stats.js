/* 学习统计：四格概况 + 未来 7 天到期分布 + 近 14 天复习活跃度（纯 SVG，无依赖）。 */

import { $, escapeHtml, loadingBlock } from "../core.js";

const S = { loading: true, data: null };

export default {
  key: "stats",
  title: "学习统计",
  icon: "📊",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    await this.load();
  },

  async load() {
    S.loading = true;
    this.render();
    try {
      S.data = await this.ctx.rpc("stats");
    } catch (e) {
      this.ctx.toast(`统计数据读取失败：${e.message}`, "error");
      S.data = null;
    }
    S.loading = false;
    this.render();
  },

  render() {
    const root = this.root;
    if (!root) return;
    if (S.loading) {
      root.innerHTML = loadingBlock("正在统计…");
      return;
    }
    const d = S.data;
    if (!d) {
      root.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>
        <div class="empty-title">统计数据读不出来</div>
        <div class="empty-text">稍后再试一次；持续失败请看下方运行日志。</div></div>`;
      return;
    }
    const c = d.counts;
    const today = d.due_series[0]?.label;
    const dueBars = [
      ...(d.due.overdue ? [{ label: "已逾期", value: d.due.overdue, color: "var(--danger)" }] : []),
      ...d.due_series.map((b) => ({
        label: b.label,
        value: b.value,
        color: b.label === today ? "var(--warn)" : "var(--info)",
      })),
    ];
    const actBars = d.activity.map((b) => ({
      label: b.label,
      value: b.value,
      color: b.label === today ? "var(--warn)" : "var(--ok)",
    }));

    root.innerHTML = `<div class="stack">
      <section class="tiles">
        ${tile("var(--info)", c.total, "收藏视频")}
        ${tile("var(--ok)", c.with_transcript, "有字幕全文")}
        ${tile("var(--warn)", c.with_summary, "已生成卡片")}
        ${tile("var(--purple)", c.mature, "长期记忆（≥21天）")}
      </section>
      <section class="tiles">
        ${tile("var(--danger)", d.due.overdue, "已逾期")}
        ${tile("var(--warn)", d.due_series[0]?.value || 0, "今日到期")}
        ${tile("var(--ok)", d.reviewed_7d, "近 7 天复习")}
        ${tile("var(--info)", `${d.lifetime.avg_interval}`, "平均记忆间隔（天）")}
      </section>
      <section class="card card-pad">
        <div class="card-head">
          <h3>未来 7 天到期分布</h3>
          <span class="sub">${d.due.overdue ? `另有 ${d.due.overdue} 张已逾期` : "没有逾期卡片，节奏很稳"}</span>
        </div>
        ${barChart(dueBars, "本周每天要复习多少张")}
      </section>
      <section class="card card-pad">
        <div class="card-head">
          <h3>近 14 天复习活跃度</h3>
          <span class="sub">累计忘过 ${d.lifetime.lapses} 次 · 复习库 ${c.learning} 张在排期</span>
        </div>
        ${barChart(actBars, "每天实际复习的卡片数")}
      </section>
      <div class="hint">数据全部来自本机数据库；「长期记忆」= 复习间隔已 ≥ 21 天的卡片。</div>
    </div>`;
  },

  async refresh() {
    await this.load();
  },
};

function tile(color, value, label) {
  return `<div class="card tile">
    <i class="tile-dot" style="color:${color}">●</i>
    <div class="tile-num">${escapeHtml(String(value ?? 0))}</div>
    <div class="tile-label">${escapeHtml(label)}</div>
  </div>`;
}

/** 纯 SVG 柱状图：宽度自适应，柱子按比例缩放；每根柱子带原生 tooltip。 */
function barChart(series, aria) {
  const n = series.length;
  if (!n) return '<div class="muted">暂无数据</div>';
  const step = 64;
  const padX = 36;
  const top = 22;
  const base = 132;
  const w = padX * 2 + step * n;
  const h = base + 34;
  const max = Math.max(1, ...series.map((b) => b.value));
  const bars = series
    .map((b, i) => {
      const x = padX + i * step + 8;
      const bw = step - 16;
      const bh = Math.round(((base - top) * b.value) / max);
      const y = base - bh;
      const tint = b.color.replace("var(", "").replace(")", "");
      return `<g class="ch-bar">
        <title>${escapeHtml(b.label)}：${b.value} 张</title>
        <rect x="${x}" y="${y}" width="${bw}" height="${Math.max(bh, b.value ? 2 : 0)}" rx="4" fill="${b.color}"/>
        ${b.value ? `<text class="ch-val ${tint}" x="${x + bw / 2}" y="${y - 6}" text-anchor="middle">${b.value}</text>` : ""}
        <text class="ch-lab" x="${x + bw / 2}" y="${base + 17}" text-anchor="middle">${escapeHtml(b.label)}</text>
      </g>`;
    })
    .join("");
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${escapeHtml(aria)}" preserveAspectRatio="xMidYMid meet">
    <line class="ch-axis" x1="${padX - 22}" y1="${base + 0.5}" x2="${w - padX + 6}" y2="${base + 0.5}"/>
    <line class="ch-grid" x1="${padX - 22}" y1="${top}" x2="${w - padX + 6}" y2="${top}"/>
    <text class="ch-max" x="${padX - 12}" y="${top + 4}" text-anchor="end">${max}</text>
    ${bars}
  </svg>`;
}
