# 收藏夹遗忘曲线 · B站版

> 你在 B 站收藏的那些"下辈子再看"，从这里开始这辈子看完。

把 **B 站收藏夹** 变成一个**会主动找你复习的知识库**：

```
同步收藏夹 → 拉取视频字幕 → LLM 生成复习卡片 → 遗忘曲线到期提醒 → 主动回忆评分 → 全文检索
```

核心思路来自认知科学：点"收藏"只会制造"学过了"的错觉（数字囤积），**主动回忆（提取练习）+ 间隔重复**才是记忆真正形成的方式。本项目用 SM-2 简化算法为每张收藏卡片安排复习时间：记得牢就隔久一点，忘了就明天再见。

## 功能

- 🖥 **图形界面**（推荐）：双击桌面图标即可用——侧栏导航、窗口内扫码登录、勾选收藏夹同步、点击式复习卡片、卡片库浏览、图表统计、搜索、填 API Key、一键开关每日提醒
- 🔐 **扫码登录**：终端二维码或 GUI 窗口扫码，cookie 只存本机
- 🔄 **增量同步**：收藏夹元数据 → CC/AI 字幕抓取 → LLM 摘要，三段式、断点续跑，单视频失败不炸全程
- 🤖 **摘要三档全覆盖**：有字幕精摘 → 无字幕批量轻摘（8条/次合并调用，省请求省成本）→ 无信息零 AI 兜底；卡片库一键「补齐缺失摘要」，增量永不重复生成
- 🧠 **遗忘曲线复习**：新卡首次学习直接读内容后评估；复习卡先回忆再看答案，按 忘了/模糊/记得 评分自动排下次时间；**键盘快捷键**（空格显示答案 / 1/2/3 评分 / S 跳过）+ **评分撤销**
- 🗂 **卡片库**：全部卡片的"书架"，状态徽章 + 筛选 + 双击详情，与复习排期独立
- 📊 **学习统计**：未来 7 天到期分布图 + 近 14 天复习活跃度图 + 累计数据
- 📤 **Anki 导出**：一键导出 `.apkg` 牌组（按 BV 号稳定去重，可反复导入）
- 🔍 **全文检索**：FTS5（trigram 中文子串）搜索标题/简介/字幕/摘要，LIKE 兜底
- 🔔 **提醒**：Windows Toast + 可选 Server酱微信推送
- 💾 **自动备份**：每日首次使用自动备份数据库，保留最近 7 份
- 🎮 **演示模式**：`demo` 内置 4 张卡片，不登录不花钱即可体验全流程

## 安装

### 方式一：一键安装（推荐，Windows 10/11，**无需安装 Python**）

从发布包解压后，双击 **`install.bat`**。安装器自动完成：

1. 把程序（独立 exe）安装到 `%LOCALAPPDATA%\BiliFavReview`（从旧版 venv 安装升级时会自动清理旧运行环境）
2. 创建桌面 / 开始菜单「收藏夹遗忘曲线」快捷方式（双击即开图形界面，无黑窗口）
3. 在 `~\.bili_fav_review\` 生成默认配置 `config.toml`
4. 询问是否注册"每日提醒"计划任务（默认 09:30 弹通知）

```bat
install.bat                     :: 交互安装
install.bat -TaskTime 21:00     :: 指定每日提醒时间
install.bat -NoTask             :: 不建计划任务
install.bat -Portable D:\BFR    :: 便携安装（只放程序，不建快捷方式/计划任务）
```

交给进阶用户：装完后命令行用法 = 直接运行安装目录里的 exe（无参数打开界面，带子命令走 CLI）：

```bat
:: 以默认安装目录为例
"%LOCALAPPDATA%\BiliFavReview\收藏夹遗忘曲线.exe" demo    :: 不登录先体验（内置演示数据）
"%LOCALAPPDATA%\BiliFavReview\收藏夹遗忘曲线.exe" login   :: 扫码登录 B 站
"%LOCALAPPDATA%\BiliFavReview\收藏夹遗忘曲线.exe" sync    :: 同步收藏夹 + 生成复习卡片
```

**卸载**：运行程序目录里的 `uninstall.bat`（自动移除计划任务、快捷方式、程序文件；数据目录可选保留或删除）。

**开发者出包**：源码目录里 `build_exe.bat` 打出 `dist\收藏夹遗忘曲线.exe`；`install.bat` 可直接把当前源码构建安装到本机；`release.bat` 生成可分发的 `dist/BiliFavReview-v*.zip`。

### 方式二：手动安装（开发模式）

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # 或 pip install -e .
.venv\Scripts\python -m bili_fav_review --help
```

> 中文显示说明：程序输出编码自动跟随控制台——交互终端（WriteConsoleW）永远正确；管道/重定向时跟随系统代码页（zh-CN 为 GBK，与 `type`/记事本一致）；计划任务等无控制台场景用 UTF-8。

## 图形界面（小白推荐）

界面采用与「桌面工作台」一致的设计语言：**左侧深石墨导航栏 + 浅色卡片式页面**，柔和模块色点缀。

安装器默认会在**桌面和开始菜单**创建「收藏夹遗忘曲线」图标，双击即开（独立 exe，无控制台窗口）。源码运行时：

```bat
.venv\Scripts\python -m bili_fav_review gui   :: 也可不带参数直接运行，默认打开界面
```

界面共 6 页（左侧导航切换）：

| 页面 | 能做什么 |
|---|---|
| 首页 | 「今天该复习了」主卡 + 大按钮（区分新卡/复习卡）、四格数据磁贴、首次使用四步引导 |
| 我的收藏夹 | 拉取收藏夹列表，点击勾选要同步的夹子，一键增量同步（后台运行 + 实时日志） |
| 复习 | 新卡直接读内容后评估；复习卡先回忆再「显示答案」，红/琥珀/绿三色评分按钮自动排下次时间；**键盘快捷键**（空格/1/2/3/S）；支持撤销上一次评分；空状态可一键把排在未来的新卡提前到今天 |
| 卡片库 | 全部卡片的"书架"：状态徽章 + 筛选 + 双击看完整内容，可与复习排期独立地随便翻看，单张"提前到今天"，一键补齐缺失摘要，**一键导出 Anki** |
| 搜索 | 搜标题/简介/字幕/摘要，双击看完整卡片，可直接跳转 B 站视频 |
| 统计 | 未来 7 天到期分布柱状图、近 14 天复习活跃度图、累计数据（忘过次数/平均间隔/长期记忆） |
| 设置 | 填 API Key/接口/模型（保存到 config.toml）；一键创建/移除每日提醒计划任务；Server酱微信推送（可选）；打开数据文件夹 |

> 桌面图标启动的是独立 exe（无控制台窗口）；程序崩溃会自动把堆栈写到 `~/.bili_fav_review/gui_error.log`。界面基于系统 WebView2（Win10/11 自带 Edge 内核），不可用时自动回退到 Edge 应用窗口或默认浏览器，同一套页面不受影响。

## 快速开始

```bash
# 0) 不登录先玩一遍（内置演示数据）
.venv\Scripts\python -m bili_fav_review demo
.venv\Scripts\python -m bili_fav_review review
.venv\Scripts\python -m bili_fav_review search 遗忘

# 1) 扫码登录 B 站
.venv\Scripts\python -m bili_fav_review login

# 2) 看看有哪些收藏夹
.venv\Scripts\python -m bili_fav_review folders

# 3) 同步（首次会让你选择收藏夹并记住）
.venv\Scripts\python -m bili_fav_review sync

# 4) 每天复习到期卡片
.venv\Scripts\python -m bili_fav_review review
```

## 配置

复制 `config.example.toml` 为 `config.toml`（放项目目录或 `~/.bili_fav_review/` 下）。**必填项只有一个**：`llm.api_key`（默认对接智谱 GLM 的 `glm-4-flash`，免费额度即可；任何 OpenAI 兼容接口如 DeepSeek/本地 ollama 改两个字段就能用）。

常用配置项：

| 配置 | 默认 | 说明 |
|---|---|---|
| `llm.api_key` | 空 | LLM 密钥（只存本机；也可 `llm.enabled = false` 关掉摘要只存字幕） |
| `sync.summaries_per_run` | 40 | 每次 sync 最多生成几张卡，控制 token 花费 |
| `sync.request_interval` | 1.0 秒 | B 站接口请求间隔，**请勿低于 0.5**，对自己账号好一点 |
| `review.new_due_days` | 0 | 新收藏当天即可学习（改 1 则排到明天） |
| `llm.batch_intro_size` | 8 | 无字幕视频批量轻摘：一次 AI 调用合并的视频数 |
| `notify.serverchan_sendkey` | 空 | Server酱 SendKey；填入后每日提醒推送微信 |

## 命令一览

| 命令 | 作用 |
|---|---|
| `gui` | 打开图形界面（日常使用推荐这个） |
| `login` | 扫码登录，保存登录态到 `~/.bili_fav_review/cookies.json` |
| `folders` | 列出账号收藏夹 |
| `sync [--folder ID] [--all] [--limit N] [--no-llm]` | 增量同步：元数据 + 字幕 + 摘要 |
| `review [--limit N]` | 复习今天到期的卡片（核心命令） |
| `due [--notify]` | 查询到期数量；`--notify` 弹系统通知；配了 Server酱则推送微信 |
| `search 关键词` | 全文搜索，`show <bvid>` 看完整卡片 |
| `stats` | 复习库统计与到期分布 |
| `export-anki [--out PATH] [--deck NAME]` | 导出 Anki 牌组（.apkg），按 BV 号去重 |
| `demo [--clear]` | 演示数据塞入/清除 |

## 每日自动提醒

安装时若跳过了计划任务，随时可补建（会覆盖旧任务）：

```bat
install.bat -TaskTime 09:30
```

任务由安装器创建，等价手动方式：

```bat
schtasks /Create /SC DAILY /ST 09:30 /TN "BiliFavReview" ^
  /TR "\"C:\Users\%USERNAME%\AppData\Local\BiliFavReview\收藏夹遗忘曲线.exe\" due --notify"
```

> 提醒任务后台静默运行（不弹黑窗口）：配置了 Server酱会推送微信；Windows Toast 通知依赖可选组件 win11toast，未安装时静默降级、不影响程序本身。
> 注意：计划任务的启动目录不是程序目录，配置文件建议放 `~/.bili_fav_review/`（安装器已默认放这里），保证读到同一份数据库。

## 工作原理与已知限制

- **字幕来源**：优先真实 CC 字幕，其次 B 站 AI 字幕（`ai-zh`），两者都没有的视频只能用标题+简介生成低保真卡片（库内会标注"无CC/AI字幕"）
- **多 P 视频**：目前只抓 P1 字幕
- **仅限普通视频**：番剧/课程（cheese）类收藏走的是另一套接口，暂不支持
- **登录态**：SESSDATA 有效期约 1 个月，失效后命令会明确提示重新 `login`
- **风控**：所有请求带 buvid 与合理间隔，遇 `-412/-352` 自动退避重试；请勿调低请求间隔
- 本项目不下载视频本体，只取公开接口的字幕与元数据，仅供个人学习

## 与相关项目的差异

- [bilibili-rag](https://github.com/via007/bilibili-rag)：收藏夹 → 可对话知识库（RAG 问答），但没有复习调度
- [bilibili-video-summary-agent](https://github.com/Cansiny0320/bilibili-video-summary-agent)：单视频摘要 CLI，无收藏夹批量、无遗忘曲线
- 本项目独有的一环是**遗忘曲线调度 + 每日到期复习闭环**：摘要不是终点，复习才是

## 项目结构

```
bili_fav_review/
├── bilibili/        # wbi 签名 / 扫码登录 / API 客户端（限速+风控退避）
├── store/           # SQLite + FTS5 检索 + SM-2 简化调度
├── commands/        # sync / review / search / stats / demo / account
├── webui/           # 图形界面：本地 HTTP 服务 + pywebview 窗口 + 零构建前端（static/）
├── summarize.py     # LLM 复习卡片生成（OpenAI 兼容接口）
└── cli.py           # 命令分发
assets/              # 图标设计源（SVG/PNG）与生成脚本
exe_entry.py         # PyInstaller 打包入口（build_exe.bat 使用）
tests/               # 单元测试
```

## Roadmap

- [x] 卡片库与统计页、Anki 导出、Server酱推送、自动备份（v0.4.0）
- [x] 界面重构为本地 WebUI + 独立 exe 分发（v0.5.0，无需 Python，安装器一键升级）
- [ ] 无字幕视频用本地 ASR（funasr/whisper）兜底
- [ ] 复习卡片跳转视频时间戳（从问题直达片段）
- [ ] 收藏夹自动监听（新收藏自动进队列）

## 隐私

cookie、数据库、API key 全部只保存在本机 `~/.bili_fav_review/`；发送给 LLM 的只有视频标题、简介与字幕文本。请勿分享 cookies.json。
