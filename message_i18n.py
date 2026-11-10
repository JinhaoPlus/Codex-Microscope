"""Structured i18n message codes for backend JSON; zh-CN fallbacks for legacy fields."""
import re

FALLBACK = {
    'common.unrecorded': '未记录',
    'context.localFilePageTitle': '会话引用的目录',
    'context.localFilePageNote': '仅列出这段会话明确引用的文件。',
    'demo.group.exec': 'exec · 编排与结果',
    'demo.group.files': '命令、文件与终端',
    'demo.group.builtin': '其他内建工具',
    'demo.group.mcp': '外部 MCP · 通用展示',
    'demo.group.edge': '补充边界',
    'errors.badSize': '请求大小不合法',
    'errors.csrf': '拒绝跨站设置请求',
    'errors.dbBusy': '暂时无法读取 {name}，正在等待恢复。请确认 Codex 数据目录可访问。',
    'errors.demoMissing': '示例不存在',
    'errors.demoUnknown': '未知演示接口',
    'errors.execMissing': '执行记录不存在',
    'errors.historyDbBusy': '备用正文数据库暂不可用，请稍后重试。',
    'errors.historyUnavailable': '状态与耗时数据库暂不可用，已保留可读取的会话内容。',
    'errors.localFileDenied': '仅允许访问此会话明确引用的文件',
    'errors.localFileGone': '原文件已移动或不存在',
    'errors.localFileTooLarge': '文件过大或不是普通文件',
    'errors.localhostOnly': '仅允许 localhost 访问',
    'errors.needJson': '需要 JSON 请求',
    'errors.noContent': '没有可读取的会话内容',
    'errors.noIndex': '未找到 Codex 会话索引，请确认 CODEX_HOME 指向已有的数据目录。',
    'errors.notFound': 'Not found',
    'errors.unexpected': '发生意外错误。',
    'errors.outsideHome': '记录位于数据目录之外',
    'errors.rolloutUnavailable': '会话记录文件不可用',
    'errors.settingsMissing': '未找到设置',
    'errors.syncFailed': '同步失败，已有缓存已保留：{detail}',
    'errors.threadMissing': '会话不存在',
    'errors.toolMissing': '工具记录不存在',
    'errors.zstdCorrupt': 'zstd 会话解压失败，文件可能损坏。',
    'errors.zstdNeed': '该会话已压缩：需要 Python 3.14+ 或安装 zstd 后重试。',
    'navigation.unnamedDirectory': '未记录目录',
    'pricing.err.creditsFormat': '官方 credits 页面格式发生变化，保留已有缓存',
    'pricing.err.creditsNoModels': '官方 credits 表未解析到模型，保留已有缓存',
    'pricing.err.download': '价格下载失败（curl {code}）：{detail}',
    'pricing.err.invalidSettings': '无效的价格设置',
    'pricing.err.needCurl': '更新价格需要系统 curl，请安装 curl 后重试；已有缓存已保留',
    'pricing.err.noOpenAIModels': '接口未返回 OpenAI 模型，保留已有缓存',
    'pricing.err.noOpenAIPrices': '接口未返回 OpenAI 单价，保留已有缓存',
    'pricing.err.positive': '金额和 credits 应为正数',
    'pricing.err.positiveRange': '金额和 credits 应为正数，最多 12 位小数且不超过 1 万亿',
    'pricing.err.ruleFields': '换算规则只需支付金额和获得 credits',
    'pricing.err.timeout': '价格下载超时，已有缓存已保留',
    'pricing.err.tls': '系统 curl 无法验证价格源的 HTTPS 证书，请检查系统证书配置；已有缓存已保留',
    'pricing.err.tooLarge': '价格响应超出大小限制',
    'pricing.err.unknownSource': '未知价格源',
    'pricing.err.usdOnly': '换算金额仅使用 USD',
    'pricing.reason.cacheWrite': '缓存写入时长未记录',
    'pricing.reason.creditsModel': 'credits 模型价格未收录',
    'pricing.reason.creditsTier': 'credits 档位价格未收录',
    'pricing.reason.inputLen': '调用输入长度未记录',
    'pricing.reason.modelMissing': '模型未记录',
    'pricing.reason.notCached': '价格尚未缓存',
    'pricing.reason.openaiModel': 'OpenAI 模型价格未收录',
    'pricing.reason.tierMissing': '速度档位未记录',
    'pricing.reason.tierPrice': '档位价格未收录',
    'pricing.reason.tierUnavailable': '此价格源未提供该档位',
    'pricing.reason.unitMissing': '所需单价缺失',
    'session.multimodal.audio': '[音频]',
    'session.multimodal.image': '[图片]',
    'session.orphanToolName': '工具结果',
    'tools.action.agentActivity': '子任务活动',
    'tools.action.agentTool': '子代理工具',
    'tools.action.agentToolFallback': '代理工具 {tool}',
    'tools.action.computer': '电脑操作',
    'tools.action.createGoal': '创建目标',
    'tools.action.dynamicTool': '动态工具 {identity}',
    'tools.action.editFile': '修改文件',
    'tools.action.execResult': '执行结果 {command}',
    'tools.action.failedSuffix': '· 失败',
    'tools.action.findInPage': '页内查找',
    'tools.action.generateImage': '生成图片',
    'tools.action.getGoal': '查看目标',
    'tools.action.imageGen': '生成或编辑图片',
    'tools.action.listResourceTemplates': '列出资源模板',
    'tools.action.listResources': '列出资源',
    'tools.action.noNewOutput': '· 无新增输出',
    'tools.action.openPage': '打开网页',
    'tools.action.orchestration': '编排脚本',
    'tools.action.readFile': '读取文件',
    'tools.action.readResource': '读取资源',
    'tools.action.readTime': '读取时间',
    'tools.action.runCommand': '运行命令{detail}',
    'tools.action.searchContent': '搜索内容',
    'tools.action.sessionInput': '向后台终端输入',
    'tools.action.sessionInteract': '后台终端交互',
    'tools.action.sessionInterrupt': '请求中断后台终端',
    'tools.action.sessionSuffix': ' · 会话 {sessionId}',
    'tools.action.sessionWait': '等待后台终端',
    'tools.action.status.completed': '已完成',
    'tools.action.status.failed': '失败',
    'tools.action.status.inProgress': '处理中',
    'tools.action.subjectFailed': '失败',
    'tools.action.targetsCount': '{count} 个目标',
    'tools.action.unknownType': '工具类型未确认',
    'tools.action.viewImage': '查看图片 {filename}',
    'tools.action.waitClock': '等待时钟',
    'tools.action.wasRunningSuffix': '· 上次记录时仍在运行',
    'tools.action.webOp': '网页操作',
    'tools.action.webSearch': '网页搜索',
    'tools.action.webSearchQueries': '{count} 条查询',
    'tools.action.webTool': '网页工具',
    'tools.action.writeFile': '写入文件',
    'tools.exec.cellAmbiguous': '此编号对应多条未结束的调用，无法确定来源。',
    'tools.exec.cellNoOrigin': '等待发出时没有可关联的运行单元。',
    'tools.exec.defaultFile': '文件',
    'tools.exec.findTools': '查找可用工具',
    'tools.exec.label.edit': '修改文件',
    'tools.exec.label.list': '列举',
    'tools.exec.label.read': '读取 {path}',
    'tools.exec.label.search': '搜索',
    'tools.exec.listLimit': ' · 前 {count} 行',
    'tools.exec.listPrefix': '列举 {path}',
    'tools.exec.readDetail': '读取 {path}',
    'tools.exec.multiLabel': '{labels} · {count} 项',
    'tools.exec.noResult': '未记录结果',
    'tools.exec.requestPrefix': '请求{label}',
    'tools.exec.searchPrefix': '搜索 {query}',
    'tools.exec.serviceError': '· 服务返回错误',
    'tools.exec.state.aborted': '用户中止',
    'tools.exec.state.failed': '编排失败',
    'tools.exec.state.imageReturned': '图片已返回',
    'tools.exec.state.pending': '待取回',
    'tools.exec.state.resultReturned': '结果已返回',
    'tools.exec.state.retrieveFailed': '取回失败',
    'tools.exec.state.terminated': '编排已终止',
    'tools.exec.state.waitInterrupted': '等待被中断 · cell 最终状态未记录',
    'tools.exec.tryWriteFail': '尝试{label} · 写入失败',
    'tools.exec.userRun': '用户{label}',
    'tools.exec.verb.add': '新增 {path}',
    'tools.exec.verb.delete': '删除',
    'tools.exec.verb.move': '移动 {old} → {new}',
    'tools.exec.waitCompleted': '等待已完成',
    'tools.exec.waitReturn': '等待编排返回',
    'tools.exec.waitTerminate': '请求终止编排',
    'tools.exec.waitUserAbort': '等待被用户中断',
    'tools.native.agent.completed': '子任务已完成{detail}',
    'tools.native.agent.interacted': '子任务发生交互{detail}',
    'tools.native.agent.interrupted': '子任务已中断{detail}',
    'tools.native.agent.started': '子任务已启动{detail}',
    'tools.native.followup': '追加子任务',
    'tools.native.interrupt': '请求中断子任务',
    'tools.native.list': '查看子任务',
    'tools.native.send': '发送子任务消息',
    'tools.native.spawn': '启动子任务',
    'tools.native.wait': '等待子任务',
    'usage.badTimezone': '无法识别统计时区',
    'usage.invalidScope': '无效的统计范围',
    'usage.unknownDimension': '未知统计维度',
    'usage.unrecordedDirectory': '未记录目录',
}

_PARAM = re.compile(r'\{(\w+)\}')


def msg(key, **params):
    return {'key': key, 'params': params}


def legacy(key, **params):
    text = FALLBACK.get(key, key)
    return _PARAM.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)


def error_payload(key, *, code=None, details=None, **params):
    payload = {'error_code': code or key.split('.')[-1], 'message': msg(key, **params)}
    if details is not None:
        payload['details'] = details
    zh = legacy(key, **params)
    if zh:
        payload['error'] = zh
    return payload


class I18nError(Exception):
  """Product error with stable message key; str() returns zh-CN fallback."""

  def __init__(self, key, *, code=None, params=None, details=None):
      self.key = key
      self.params = dict(params or {})
      self.code = code or key.split('.')[-1]
      self.details = details
      super().__init__(legacy(key, **self.params))


class PricingError(I18nError, ValueError):
    pass


class PricingOSError(I18nError, OSError):
    pass


class UsageError(I18nError, ValueError):
    pass


class SessionIOError(I18nError, ValueError):
    pass


class SessionIORuntime(I18nError, RuntimeError):
    pass


class DatabaseUnavailable(I18nError, RuntimeError):
    pass


def i18n_error(exc):
    if isinstance(exc, I18nError):
        return error_payload(exc.key, code=exc.code, details=exc.details, **exc.params)
    return error_payload('errors.unexpected', code='internal', details={'diagnostic': str(exc)})
