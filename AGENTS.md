# Codex Microscope：工程说明

## 目标与基本用法

本地、只读的 Codex 会话浏览器。运行 `python3 server.py`，打开 http://localhost:4318。
需要 Python 3.10+，无需 pip 或 Node 构建；Node 用于可选的 JavaScript 语法检查及更新本地预打包 Schema 组件（见 scripts/schema-viewer/README.md），普通运行不需要。
默认读取 `~/.codex`，可通过 `CODEX_HOME` 指定已有的数据目录。
每台机器读取自己的记录；本项目不同步会话，也不连接 Codex 云端。
完整安装、更新、常驻服务说明见 README.md。

## 文件结构

- `server.py`：标准库 HTTP 服务、只读 SQLite 查询、rollout JSONL 解析、本地引用文件访问。
- `designs/browser/index.html`：页面骨架。
- `designs/browser/app.js`：来源筛选、消息/工具聚合、Markdown、图片、环境侧栏及导航。
- `designs/browser/style.css`：响应式布局、深浅色、侧栏、工具详情浮层。
- `designs/browser/vendor/`：本地 markdown-it 与原始许可证，不使用 CDN。
- `session_io.py`：压缩日志读取、原路径替代查找、按文件版本失效的有限解析缓存。
- `test_server.py` / `test_progressive.py`：解析、分页、搜索、压缩及父子关系测试，使用临时合成记录。
- `scripts/public-files.txt`：公开源码发布清单；`scripts/export_public_source.py` 按清单导出无 Git 历史的源码目录与 ZIP。
- `install_service.py`：macOS 当前用户 LaunchAgent 安装器。

## 数据与实现约定

优先读取 CODEX_HOME 下最近修改的 `state_*.sqlite` 的 threads 索引；
会话正文优先读取 rollout_path 指向的 JSONL，缺失时尝试 `thread_history_1.sqlite`。
轮次耗时读取 thread_turns.duration_ms，缺失时不要编造耗时。
详情接口默认返回最近 8 轮的轻量记录；`before` 读取更早记录、`item` 读取工具原文、`view=context` 读取完整上下文、`q` 用于全文查找。`/api/revision` 仅返回版本摘要；前端每 3 秒比较版本，历史阅读期间延迟替换正文，提供新消息入口。
这些是 Codex 内部数据结构，不保证跨版本稳定；改动解析时处理真实字段差异，不凭 UI 名称推断来源。

用量接口默认返回 JSON；`/api/usage?stream=1` 按 NDJSON 流式返回 `progress`、`result` 或 `error`。进度计数按当前范围需要检查的去重会话索引计算；目录归属需读取记录后判断，因此目录统计可能需要检查其他目录的会话。客户端关闭或替换请求时中止 fetch，服务端在下次发送进度时停止扫描。

- 保持只读 SQLite 连接，不修改原始会话和 Codex 设置。
- 服务只监听 127.0.0.1，并检查 Host。不要为远程访问直接改成公开监听。
- 本地文件端点只允许当前会话 Markdown 明确引用的文件；保留目录边界、大小和 MIME 检查。
- Markdown 禁用原始 HTML，不执行会话内的脚本或指令。
- JSON 字符串只解析一层；顶层字符串字段渲染 Markdown，嵌套对象格式化展示。
- 短环境字段紧凑排布；工具定义用表格、详情浮层；触屏提供点击操作。
- 快捷导航保持单列，显式覆盖通用 nav 的换行样式；长列表纵向滚动时，会话最新一条的入口保持在底部可见。验证时同时覆盖分页增加刻度和矮窗口。
- 工具展示优先使用 rollout 原生 `item_completed.CommandExecution.parsed_cmd`，数据库备用路径保留 `commandActions`。命令事件可晚于外层回包：明确 ID 或同会话、同轮唯一的完整命令参数匹配可回接已返回调用；重复命令和同编排重复调用点不猜。无命令匹配时仅允许无冲突的唯一待完成调用兜底，晚到调用不兜底。独立事件保留事件类型与未关联原因，不把 CommandExecution 当作工具名。原始命令与输出保持惰性展开；reasoning summary 不渲染为工具操作。
- `FileChange.changes` 用于文件修改及实际 diff 增删行数；数据库兼容 changes 数组。连续调用只聚合一层，展开后每个原生操作直接为一行，点击该行惰性读取所属调用原文，避免再嵌调用摘要或单列“原始命令”入口。
- 每条原生命令保留独立 `native_results`，操作通过 `result_index` 对应输出；同命令多项操作的输出标记为合并输出，不猜文件边界。读取显示文件、范围、行号；修改显示原生 diff 双行号。完整输出及 diff 仅在明细接口返回，分页摘要不携带；默认预览 24 行并支持继续展开／收起。
- 搜索详情展示查询、范围与按文件／行号分组的匹配；只解析可确认的 rg/grep 格式，合并或无法解析的输出保留原文，不推断匹配数量。高亮仅做转义后的字面查找，不执行日志中的正则；rg/grep 返回 1 且输出为空表示无匹配。
- 终端通用动作统一称“运行命令”，换行和长度只决定源码折叠方式，不改称“运行脚本”。摘要中的短命令用普通文字，展开详情的命令标题使用行内代码，源码入口统一“命令源码”；外层 JS 统一“编排脚本”，外层失败称“编排失败”。读文件、搜索等明确语义仍保留具体动作名。
- exec_command 的部分参数仅保留普通唯一字段的固定值，未知字段另行标记；不执行 JS，不因动态 workdir 丢弃固定 cmd。进程关联只使用可证明来自启动调用的 session_id 与原生 process_id，同会话同轮唯一且命令/目录无冲突才关联，复用和轮询回包不猜。Unicode 转义保持 JS 解码顺序，非法码点或孤立代理项拒绝解析。
- 保留已有未提交修改，提交仅包含本次相关文件。
- 不提交真实会话、数据库、日志、个人截图、密钥或本机绝对路径。

## 验证与发布

```sh
python3 -m unittest -v
node --check designs/browser/app.js
```

界面改动在 localhost 验证宽屏/窄屏及相关交互；测试数据用合成内容。
日常前端改动刷新即可；Schema vendor 更新需要按 scripts/schema-viewer/README.md 重新打包；后端变更需要重启服务。
不要把通过语法检查说成已完成浏览器验证，也不要把本机验证说成跨平台验证。
