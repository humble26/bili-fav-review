/* 设置页：AI 摘要配置、每日提醒（计划任务）、数据目录、微信推送。 */

import { $, escapeHtml } from "../core.js";

export default {
  key: "settings",
  title: "设置",
  icon: "⚙",

  async mount(root, ctx) {
    this.ctx = ctx;
    this.root = root;
    const d = await ctx.rpc("settings");
    const s = d.settings;
    const taskOn = !!d.task?.enabled;

    root.innerHTML = `
      <div class="grid-2">
        <section class="card card-pad">
          <div class="card-head">
            <h3>AI 摘要设置</h3>
            <span class="sub">任何 OpenAI 兼容接口均可</span>
          </div>
          <label class="field">
            <span class="field-label">API Key</span>
            <input class="input" id="set-key" type="password" autocomplete="off"
                   placeholder="粘贴你的 API Key" value="${escapeHtml(s.api_key)}" />
          </label>
          <label class="field">
            <span class="field-label">接口地址 base_url</span>
            <input class="input" id="set-base" value="${escapeHtml(s.base_url)}" />
          </label>
          <label class="field">
            <span class="field-label">模型 model</span>
            <input class="input" id="set-model" value="${escapeHtml(s.model)}" />
          </label>
          <div class="row" style="justify-content: space-between">
            <span class="hint">免费推荐：智谱 https://open.bigmodel.cn/api/paas/v4 + glm-4-flash<br />
              DeepSeek：https://api.deepseek.com/v1 + deepseek-chat</span>
            <button class="btn btn-primary" id="btn-save-ai" type="button">💾 保存配置</button>
          </div>
          <p class="hint" style="margin-top: 10px">
            配置文件：<span class="kv">${escapeHtml(s.config_path)}</span>
          </p>
        </section>

        <section class="card card-pad">
          <div class="card-head">
            <h3>每日提醒</h3>
            <span class="badge" id="task-badge">${taskOn ? "已开启 ✔" : "未开启"}</span>
          </div>
          <div class="row">
            <span class="hint">每天</span>
            <input class="input" id="task-time" style="width: 86px" value="09:30" />
            <span class="hint">弹出复习提醒</span>
          </div>
          <div class="row" style="margin-top: 10px">
            <button class="btn" id="btn-task-create" type="button">创建 / 更新提醒</button>
            <button class="btn btn-ghost" id="btn-task-remove" type="button">移除提醒</button>
          </div>
          <p class="hint" style="margin-top: 10px">
            用 Windows 计划任务实现，到点弹系统通知（装了 win11toast 效果最好）；
            配了 Server酱 会同时把到期数量推到微信。
          </p>
        </section>

        <section class="card card-pad">
          <div class="card-head"><h3>数据</h3></div>
          <p class="hint">所有数据都在本机，不上传任何服务器：</p>
          <p class="kv mono-path" style="margin-top: 7px">${escapeHtml(ctx.state.boot?.data_dir || "")}</p>
          <div class="row" style="margin-top: 11px">
            <button class="btn" id="btn-open-data" type="button">打开数据文件夹</button>
            <button class="btn btn-ghost" id="btn-open-exports" type="button">打开导出文件夹</button>
          </div>
        </section>

        <section class="card card-pad">
          <div class="card-head">
            <h3>微信推送（可选）</h3>
            <span class="sub">Server酱</span>
          </div>
          <label class="field">
            <span class="field-label">SendKey</span>
            <input class="input" id="set-sendkey" type="password" autocomplete="off"
                   placeholder="sct.ftqq.com 免费申请" value="${escapeHtml(s.sendkey)}" />
          </label>
          <div class="row" style="justify-content: space-between">
            <span class="hint">保存后，每日提醒会把到期数量推到微信</span>
            <button class="btn" id="btn-save-push" type="button">💾 保存</button>
          </div>
        </section>
      </div>`;

    $("#btn-save-ai", root).onclick = () => this.saveAi();
    $("#btn-task-create", root).onclick = () => this.taskCreate();
    $("#btn-task-remove", root).onclick = () => this.taskRemove();
    $("#btn-save-push", root).onclick = () => this.savePush();
    $("#btn-open-data", root).onclick = () => this.openPath("data");
    $("#btn-open-exports", root).onclick = () => this.openPath("exports");
  },

  async refresh() {
    await this.mount(this.root, this.ctx);
  },

  async saveAi() {
    const { ctx } = this;
    try {
      const d = await ctx.rpc("settings_save", {
        api_key: $("#set-key", this.root).value,
        base_url: $("#set-base", this.root).value,
        model: $("#set-model", this.root).value,
      });
      ctx.toast(`配置已保存到 ${d.settings.config_path}`, "success");
    } catch (e) {
      ctx.toast(`保存失败：${e.message}`, "error");
    }
  },

  async savePush() {
    try {
      await this.ctx.rpc("push_save", { sendkey: $("#set-sendkey", this.root).value });
      this.ctx.toast("微信推送配置已保存", "success");
    } catch (e) {
      this.ctx.toast(`保存失败：${e.message}`, "error");
    }
  },

  async taskCreate() {
    try {
      const r = await this.ctx.rpc("task_create", { time: $("#task-time", this.root).value });
      $("#task-badge", this.root).textContent = "已开启 ✔";
      this.ctx.toast(`每日提醒已开启：每天 ${r.time}`, "success");
    } catch (e) {
      this.ctx.toast(`创建失败：${e.message}`, "error");
    }
  },

  async taskRemove() {
    try {
      const r = await this.ctx.rpc("task_remove");
      $("#task-badge", this.root).textContent = r.enabled ? "已开启 ✔" : "未开启";
      if (r.removed) this.ctx.toast("已移除每日提醒", "info");
      else this.ctx.toast("当前没有已创建的每日提醒", "warn");
    } catch (e) {
      this.ctx.toast(`移除失败：${e.message}`, "error");
    }
  },

  async openPath(kind) {
    try {
      const r = await this.ctx.rpc("open_path", { kind });
      if (!r.ok) this.ctx.toast(r.error, "warn");
    } catch (e) {
      this.ctx.toast(e.message, "error");
    }
  },
};
