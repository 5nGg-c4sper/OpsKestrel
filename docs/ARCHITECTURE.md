# SOC Agent Architecture

## 执行链路

```text
任务 JSON
  -> TaskDefinition
  -> TaskRunner
  -> SafetyPolicy
  -> ActionExecutor
  -> MacOSEnvironment
  -> QwenVisionProvider
  -> ReportWriter
```

批量执行：

```text
SuiteRunner
  -> TaskRunner
  -> 每个任务独立报告和截图
  -> 汇总结果与退出码
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `soc_agent/task_models.py` | 任务、步骤和执行结果的 Pydantic 模型 |
| `soc_agent/runner.py` | 步骤编排、超时、确认、截图和结果记录 |
| `soc_agent/actions/executor.py` | 将确定性步骤分发给环境适配器 |
| `soc_agent/environments/macos.py` | 封装应用、键鼠、截图和等待操作 |
| `soc_agent/providers/qwen.py` | 调用 Qwen 完成截图验证 |
| `soc_agent/safety/policy.py` | 阻止危险快捷键和敏感应用 |
| `soc_agent/reporting/report.py` | 持久化 JSON 报告和截图 artifacts |
| `soc_agent/suite.py` | 顺序执行多个任务并汇总结果 |
| `soc_agent/cli.py` | 参数解析和依赖装配 |
| `soc_agent/config.py` | 从环境变量加载并验证运行配置 |

## 任务动作

- `open_app`：按名称打开应用
- `write`：输入文本
- `press`：发送按键或组合键
- `click`：使用 `0-1` 归一化坐标点击
- `wait`：等待指定时间
- `verify_vision`：截图并请求 Qwen 判断
- `done`：标记任务完成

## 数据与隐私

- `.env` 不进入 Git
- API Key 不出现在配置对象的字符串表示中
- 报告和截图写入 `reports/`，默认不提交到 Git
- 屏幕截图会上传到配置的视觉模型服务
- 测试和自动化操作前应关闭短信、邮件、银行等隐私窗口

## 失败处理

任务状态：

- `passed`：所有步骤成功
- `failed`：动作、模型或验证失败
- `timed_out`：超过任务总时限
- `cancelled`：安全策略或人工确认拒绝

失败步骤会记录错误信息和可用截图。批量任务默认继续执行后续任务，也可以通过
`--stop-on-failure` 提前停止。
