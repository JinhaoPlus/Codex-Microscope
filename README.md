# Codex Microscope

本地、只读的 Codex 会话浏览器，适配桌面和手机屏幕。Python 标准库服务 + 原生 JavaScript，无 pip/npm 安装步骤，Markdown 库随项目提供。不属于 OpenAI 官方产品。

## 安装与运行

需要 Python 3.10+，以及本机已有的 Codex 会话记录。普通 JSONL 无额外依赖；压缩日志需要 Python 3.14+ 的标准库 zstd，或系统安装 `zstd` 命令（macOS 可用 `brew install zstd`）。缺少解压支持时页面会明确提示。

更新价格数据需要系统 `curl`（macOS 自带；其他系统可通过包管理器安装）。下载使用 curl 的 HTTPS 与证书配置，不依赖 Python 的根证书安装，始终校验证书；不读取用户 `.curlrc`。缺少 curl、下载失败或证书校验失败时，会明确提示并保留已有价格缓存。浏览已有记录不需要 curl。

macOS 建议使用 Homebrew Python。可运行 `python3 diagnose_sqlite.py` 检查当前运行时：本机系统 Python 的 SQLite 在 WAL 辅助文件缺失时，只读查询会报 `unable to open database file`；Codex 再次写入并创建辅助文件后才恢复。若 `readable_without_sidecars` 为 `false`，请换用通过检查的 Python，并用同一个解释器运行服务与安装器。诊断只操作临时合成库，不访问真实会话。只读连接不修改会话表；标准 SQLite 仍可能创建用于协调并发读取的 `-wal`、`-shm` 辅助文件。

```sh
git clone https://github.com/JinhaoPlus/Codex-Microscope.git
cd Codex-Microscope
python3 server.py
```

打开 [localhost:4318](http://localhost:4318)。也可以下载源码 ZIP，解压后在项目目录运行同一命令。

```sh
# 可选：自定义端口或数据目录
python3 server.py --port 4320
CODEX_HOME=/path/to/your/codex python3 server.py
```

开发验证用工具案例库：直接打开 [本地 demo](http://localhost:4318/demo)；正式页面不提供入口。它可以在没有任何真实会话的机器上运行。所有记录、命令输出和图片均为合成内容，不读取真实会话。可按工具名、案例标题或案例来源搜索，地址栏的 `#案例名` 能直接定位。推荐先看[事件晚到](http://localhost:4318/demo#late-command)、[无法关联的执行记录](http://localhost:4318/demo#unlinked-command)、[长脚本与短输出](http://localhost:4318/demo#long-script)、[脚本与并行输出](http://localhost:4318/demo#parallel-image)、[数据库里的组合命令](http://localhost:4318/demo#database-actions)、[等待中断后取回结果](http://localhost:4318/demo#wait-interrupted)和[MCP 的混合返回](http://localhost:4318/demo#mcp-blocks)。详情中的 JSON 可以切换到「日志原文」，查看对应的合成记录。

每台电脑读取自己的 Codex 数据，不会同步另一台电脑的会话。复制整个项目不需要复制数据库。当前主要在 macOS 验证；其他系统的 Python 服务未完成实机验证。

“用量与成本”覆盖会话、目录、全部记录和本轮入口：会话顶部只统计当前会话；按目录组织时，目录旁的入口统计该目录；左侧底部的入口统计全部记录；本轮入口定位对应轮次。各入口共用同一窗口，通过顶部面包屑返回上级、通过明细逐级下钻。目录按调用时的工作目录精确归属，不包含子目录；会话内切换工作目录时，相应调用归入实际目录。总量、日期／小时趋势和成本估算均限定在所选范围内。趋势图的堆叠柱表示 Token 类型，折线表示估算成本；左轴为 Token、右轴为当前成本单位，两轴独立缩放。无法估算的时段断线，部分估算使用空心点和虚线，不把未知成本当作零。

侧栏目录名称优先使用数据目录内 `.codex-global-state.json` 中 `local-projects` 的工作空间名称，仅精确匹配 `rootPaths`。没有对应名称、记录不可读或同一路径有多个不同名称时，显示目录最后一级名称；不按路径格式推断“家目录”等标签。分组仍按完整工作目录区分。

成本设置支持“credits 消耗 · 折算成本”和“API 等价成本”两种口径。credits 口径同时展示消耗和折算成本：先使用官方缓存费率估算 credits，再按用户设置的 `支付金额 ÷ 获得 credits` 折算。仅需填写支付金额（固定 USD）和获得的 credits；仅保存一条全局规则，再次保存直接更新；设置保存在本机 `.local/pricing/settings.json`，不会同步或提交。默认不预填购买价格；尚未设置规则时只显示 credits，并提示配置。换算规则统一应用到历史统计，不按购买时间分摊、不换汇，结果是等价金额而非实际账单；未匹配到模型或速度档位的用量继续标记为未估算。

每日热度网格按年展示当前统计范围的金额、Token 总量或各 Token 类型，指标选择会保存在浏览器。颜色按所选年份和指标的每日最大值线性分为四级；无已记录用量为灰色、无法估价为斜纹、部分估价为虚线边框。点击日期下钻后，网格切为当天 24 小时热度；返回全部日期时恢复年度网格。图表浮层即时显示日期、金额、Token 数量及类型占比；触屏先点看详情，再通过浮层按钮进入小时明细。

统计时显示加载圈、已检查会话数和进度条，进度来自实际扫描数量，不表示剩余时间。关闭窗口或切换范围会取消当前请求；失败后可重试。系统开启“减少动态效果”时停止旋转，保留文字与进度。

缓存命中率展示于范围汇总和日／小时浮层，按缓存读取 Token 除以输入总量计算。输入总量包含未缓存输入、缓存读取和缓存写入，不包含输出；跨轮先汇总再相除，无输入时显示“—”。

## 界面语言

支持简体中文与 English。侧栏底部可选择语言或“跟随浏览器”；切换会刷新页面，当前会话地址与已保存的显示偏好保留，临时搜索、弹框和滚动位置会重置。选择只保存在当前浏览器，不修改 Codex 设置。

同一套页面和代码加载本地语言配置；会话原文、命令、输出、文件路径及原始 JSON 保持原样。界面语言不改变统计时区、金额币种或价格换算规则。Schema Viewer 的上游规范标签沿用英语，详见 [第三方界面说明](docs/i18n-third-party.md)。

翻译配置位于 `designs/browser/locales/`，元数据记录每个 key 的用途与命名参数。修改译文后运行 `python3 scripts/check_locales.py`；新增语言需填写配置并通过完整度检查，再在 manifest 中启用。不要复制页面或业务脚本。

## 功能

- 工具调用优先按原生操作明细展示读取文件、读取技能、搜索和修改文件；修改行数来自实际 diff。连续调用聚合一层，展开后逐项展示，点击操作行查看原始调用与输出。缺少结构化明细时沿用命令摘要兜底，思考摘要不混入工具组。
- 读取详情展示文件、读取范围、命令和带行号的输出预览；修改详情展示文件、增删统计、带旧／新行号的 diff 与执行反馈。默认预览 24 行，支持展开和收起，原始调用可单独查看。每条原生命令对应自己的输出；同一命令读取多个文件时明确标注合并输出。

- 按来源筛选、搜索标题/路径/ID、查看归档记录；子代理标题兜底。
- 合并连续 Codex 消息，工具调用聚合折叠，显示有记录的轮次耗时。
- Markdown、表格、本地引用链接、图片缩略图与原地预览。
- 环境与上下文侧栏：紧凑环境字段、可展开长文、工具定义表格及详情浮层、全屏与刻度导航。
- 深浅色、窄屏布局；所有静态资源本地加载。
- 默认加载最近 8 轮，向上滚动或点击按钮加载历史；工具输入/输出展开时才读取。
- 每 3 秒检查本地版本变化，同步会话列表与正文。底部自动跟随；阅读历史时有新内容才显示提示，回到底部立即隐藏。搜索或展开工具时暂缓替换正文，点击新消息提示可跳到最新。后台标签恢复后补更新。
- 会话内搜索覆盖未加载的正文和工具输出，支持逐个跳转；环境侧栏单独读取完整上下文。
- 根据记录中的父线程 ID 关联主会话与子代理；关系入口和启动工具中的子代理入口先打开概况弹框，展示状态、模型、目录及最近消息摘录。关闭后保留当前阅读，点击“打开完整会话”才跳转。任务路径仅与记录中的 agent_path 精确匹配。
- 工具详情区分命令、补丁、MCP 和检索参数；显示已记录的退出码、补丁增删颜色及输出截断提示。

## 数据范围与限制

默认读取 `$CODEX_HOME`（未设置时为 `~/.codex`）中最近修改的 `state_*.sqlite`，所有 SQLite 连接只读。优先读取会话 rollout JSONL；支持按文件头识别 zstd，并在原路径缺失时查找 `.jsonl.zst` 替代文件，两者都不存在时尝试 `thread_history_1.sqlite`。

覆盖索引内的来源与归档记录；不扫描孤立 JSONL，不读取其他机器或纯云端会话。来源标签依据 source/originator，不把 `vscode` 猜成某个具体客户端。没有保存的正文、图片、耗时或加密推理无法还原。

按需加载目前针对传输与浏览器渲染。服务端首次仍完整解析单个会话，按路径、修改时间、大小和 inode 缓存最近 3 个解析结果；文件变化会重新解析，并非逐行增量解析。主动全文搜索会加载全部对话及命中的工具内容，极长记录可能需要更多时间和内存。

Codex 的 SQLite 表和 JSONL 属于内部格式；不同版本缺少表或字段时可能报错，需要适配。刷新按钮重新读取记录，不修改会话。

## 常驻服务（macOS）

在已克隆的目录中运行：

```sh
python3 install_service.py
```

安装到当前用户的 LaunchAgents，登录后自动启动、退出后恢复。安装器记录当前 Python 和项目的绝对路径，移动项目或更换 Python 后需要重新运行安装器。安装前先停止占用 4318 的旧服务。

```sh
# 状态
launchctl print gui/$(id -u)/local.codex-session-browser
# 更新代码后重启
git pull --ff-only
launchctl kickstart -k gui/$(id -u)/local.codex-session-browser
# 停用
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/local.codex-session-browser.plist
# 重新启用
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.codex-session-browser.plist
```

日志位于 `~/Library/Logs/CodexSessionBrowser/`。睡眠、关机、退出登录期间不可访问。旧机器若使用其他服务 Label，请继续用原 Label 管理，不要重复安装。

## 访问边界

仅监听 `127.0.0.1`，检查 Host，不提供登录认证。不要直接暴露到公网或无认证反向代理。
手机上的 localhost 指向手机本身；响应式布局不代表手机可直接访问电脑。远程访问需另行设置可信隧道与认证。
本地文件只允许访问当前会话 Markdown 明确引用的路径，单文件上限 32 MB；目录页只列出被引用的文件。

## 开发

工程结构与维护约定见 [AGENTS.md](AGENTS.md)。

```sh
python3 -m unittest -v
python3 scripts/check_locales.py
# 可选，需要 Node.js
node --check designs/browser/app.js
```

前端刷新即生效；后端修改需重启服务。`vendor/markdown-it.min.js` 使用 MIT 许可证，原始声明见同目录 `markdown-it.LICENSE`。

操作图标统一采用 Lucide SVG，以本地静态资源提供；来源记录在 `designs/browser/vendor/lucide-icons.js`，许可证见同目录 `lucide.LICENSE`。图标使用统一描边，强度仪表盘基于 Lucide Gauge 保留动态比例；品牌图标、统计图形和状态点独立呈现。不需要 React。

搜索操作提供独立详情：展示搜索内容、范围、命令、匹配文件与行号，简单关键词高亮；支持搜索结果展开／收起。无匹配、执行失败、合并输出分别呈现，无法可靠拆分时保留原文，原始调用仍可查看。

读取详情按文件扩展名使用本地 Highlight.js 11.11.1 高亮，来源为 npm `@highlightjs/cdn-assets`；许可证见 `designs/browser/vendor/highlight.LICENSE`。合并输出按当前读取文件的扩展名着色，保留合并提示及输出行号，不拆分或推断文件边界。未知类型及超过 60,000 字符的预览按纯文本展示。

一般终端操作统一称“运行命令”，不按换行切换名称；摘要中的短命令用普通文字，展开详情的命令标题使用行内代码，多行或长命令折叠为“命令源码”。详情区分命令源码、调用参数与输出；外层 JavaScript 称“编排脚本”，其失败称“编排失败”。外层 `Script completed` 不代表命令成功，执行会话句柄表示本次返回时仍在运行，明确退出码单独展示。批量或动态调用无法确认结果归属时保留未确认状态。命令源码按 Shell 着色，编排代码及 js 工具参数中的 `code` 按 JavaScript 着色；不执行会话中的代码。

工具定义中的入参 Schema 仅在全屏详情中展示，采用本地预打包的官方 Stoplight JSON Schema Viewer；首次打开时按需加载，使用 Shadow DOM 隔离样式，并跟随深浅色。保留原始 Schema 折叠入口，加载失败时仍可读取；不会联网解析外部引用。组件的规范支持有版本边界，不代表完整支持所有新版 JSON Schema。普通安装运行仍无需 Node；仅更新此组件时需要 Node/npm，版本、构建和许可证说明见 [scripts/schema-viewer/README.md](scripts/schema-viewer/README.md)。

## 隐私与联网

会话读取、搜索和用量聚合在本机进行。程序不上传会话内容，也不连接 Codex 云端。
更新价格时，后端通过 HTTPS 下载所选公开来源的数据：

- LiteLLM：`raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`
- models.dev：`models.dev/api.json`
- credits：`learn.chatgpt.com/docs/pricing.md`

价格请求不附带会话正文、目录或用量数据；远端仍会看到通常的网络请求信息（例如 IP 地址）。
价格快照和换算设置保存在本机 `.local/pricing/`。未下载价格数据时，相关金额可能无法估算。
本地浏览器中会显示会话原文和明确引用的文件；分享截图、复制内容或录屏前，请自行检查敏感信息。工具凭据遮盖只覆盖可识别字段和格式，不能替代完整脱敏。

## 许可证与贡献

项目原创代码及自有图标采用 [MIT 许可证](LICENSE)。第三方组件保留各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
本项目是独立工具，不属于 OpenAI 官方产品，也不表示获得其背书。

提交问题或补丁时，请使用合成数据复现，不附上真实会话、数据库、个人截图、密钥或本机路径。
内部日志格式可能随 Codex 更新而变化；反馈兼容性问题时，请注明系统、Python 和 Codex 版本。
当前主要在 macOS 验证，其他系统尚未完成实机验证。

如需导出无开发历史的源码发布包，运行 `python3 scripts/export_public_source.py`。
导出仅包含 `scripts/public-files.txt` 明确列出的文件，不包含 `.git`、内部调查文档或本地数据。

多语言浏览器回归使用合成 API 数据，不读取真实会话。安装 Schema 构建工具的可选依赖并启动本地服务后，可运行：

```sh
I18N_TEST_URL=http://localhost:4318 I18N_TEST_BROWSER=/path/to/chrome node scripts/verify_i18n_ui.cjs
```

检查覆盖中英、1280px/390px、延迟加载、预览、统计、错误和本地目录页；不代表其他操作系统已完成验证。
