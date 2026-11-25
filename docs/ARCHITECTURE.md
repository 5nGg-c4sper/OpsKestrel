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
  -> SuiteReportWriter 汇总报告
  -> 汇总结果与退出码
```

数据驱动执行：

```text
Dataset JSON
  -> load_dataset
  -> CSV data source -> TaskCaseDefinition
  -> DatasetRunner
  -> 每个 case 调用 run_task
  -> 每个 case 独立任务报告和截图
  -> DatasetReportWriter 汇总报告
```

工作流定义：

```text
Workflow JSON
  -> load_workflow
  -> 解析共享参数
  -> 解析并校验有序 task_files 和 cleanup_task
  -> LoadedWorkflow
  -> WorkflowRunner
  -> 按顺序执行 TaskRunner
  -> 失败后停止主任务并执行 cleanup
  -> WorkflowResult
```

Dataset 目标加载：

```text
Dataset JSON
  -> task 或 workflow 互斥目标
  -> 相对目标路径解析
  -> DatasetTargetType + 绝对 target_path
  -> task_path / workflow_path 兼容视图
  -> DatasetRunner 按目标类型执行
  -> TaskResult 或 WorkflowResult
  -> dataset 汇总报告
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `soc_agent/task_models.py` | 任务、数据源、工作流定义和执行结果的 Pydantic 模型 |
| `soc_agent/runner.py` | 步骤编排、超时、确认、截图和结果记录 |
| `soc_agent/actions/executor.py` | 将确定性步骤分发给环境适配器 |
| `soc_agent/environments/macos.py` | 封装应用、键鼠、截图和等待操作 |
| `soc_agent/providers/qwen.py` | 调用 Qwen 完成截图验证 |
| `soc_agent/safety/policy.py` | 阻止危险快捷键和敏感应用 |
| `soc_agent/reporting/report.py` | 持久化 JSON 报告、截图和失败诊断日志 |
| `soc_agent/reporting/dataset_report.py` | 持久化数据集汇总报告 |
| `soc_agent/reporting/suite_report.py` | 持久化套件汇总报告 |
| `soc_agent/reporting/workflow_report.py` | 持久化工作流汇总报告 |
| `soc_agent/suite.py` | 顺序执行多个任务并汇总结果 |
| `soc_agent/datasets.py` | 加载数据集并解析任务路径 |
| `soc_agent/data_sources.py` | 将 CSV 行转换为数据集 case 和任务参数 |
| `soc_agent/dataset_runner.py` | 顺序执行数据集 case、重试和状态聚合 |
| `soc_agent/workflows.py` | 加载工作流、解析共享参数和子任务路径 |
| `soc_agent/workflow_runner.py` | 预检参数、顺序执行子任务并汇总工作流结果 |
| `soc_agent/cli.py` | 参数解析和依赖装配 |
| `soc_agent/config.py` | 从环境变量加载并验证运行配置 |

## CI 边界

- Ubuntu 单元测试工作流在每次 push 和 pull request 时运行。
- 真实 GUI 冒烟工作流只允许 `workflow_dispatch` 手动触发。
- GUI 工作流固定使用 `self-hosted`、`macOS`、`soc-gui` 标签，并串行执行。
- 执行前检查登录态桌面、Accessibility、Screen Recording 和 API Key。
- GUI 报告默认只保留在 Runner 本机；截图 artifact 上传必须显式选择。

## 任务动作

- `open_app`：按名称打开应用
- `activate_app`：将已有或已打开的应用切换到前台
- `close_document`：关闭应用前台文稿，可显式选择是否保存
- `approval`：显式人工审批节点，批准继续、拒绝取消
- `write`：输入文本
- `press`：发送按键或组合键
- `click`：使用 `0-1` 归一化坐标点击
- `wait`：等待指定时间
- `verify_vision`：截图并请求 Qwen 判断
- `done`：标记任务完成

`verify_vision` 支持期望布尔结果、最多 5 次验证尝试和可配置重试间隔。
数据集 case 可选择对失败结果重试，取消和超时结果不会自动重试。
普通步骤可以配置视觉 `condition`。条件未命中时按跳过处理，条件验证异常时
任务失败，从而区分“业务不适用”和“判断过程本身出错”。
条件诊断保存在 `StepResult` 的 `condition_*` 字段中，条件截图使用独立 artifact
文件名，避免覆盖普通视觉验证截图。
确定性动作可配置 `loop.count` 和 `loop.delay_seconds`。循环结果记录配置次数、
实际完成次数和间隔；`verify_vision`、`done` 不允许配置循环。
任务可按 `setup_steps → steps → cleanup_steps` 三阶段执行。每个
`StepResult.phase` 标识所属阶段；cleanup 在主流程结束或失败后都会执行。
审批节点的 `approval_prompt` 和 `approval_result` 会写入步骤报告；审批文本与
普通动作节点一样支持 `${参数}` 渲染。

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

非成功任务会额外写入 `failure.log`。任务 JSON 报告通过 `failure_log` 字段引用
日志位置；套件汇总报告保留每个嵌套任务的状态、任务报告路径和失败日志路径，
数据集汇总报告还保留实际尝试次数和是否提前停止。套件报告使用
`<timestamp>-<suite-name>.json` 命名，清理文件名中的非法字符，并通过数字后缀
避免覆盖已有报告。

数据集既可使用内联 `cases`，也可使用 CSV `data_source`。CSV 在加载阶段完成表头
校验、参数列映射、空值检查和 case 名称去重，然后转换为现有
`TaskCaseDefinition`。执行层不需要区分内联 case 和 CSV case。
每个 CSV case 都独立执行任务定义中的 `setup_steps`、主流程和
`cleanup_steps`，从而保证多行执行之间不会共享未清理的文本编辑状态。
数据集目标必须且只能声明 `task` 或 `workflow` 之一；Workflow 目标模式目前只
完成严格模型契约、加载期路径解析和逐 case 执行。`LoadedDataset` 统一携带
`target_type` 和 `target_path`，同时保留 `task_path` 与 `workflow_path` 属性，
避免现有任务数据集调用方立即被破坏。`TaskCaseResult` 根据目标保存
`task_result` 或 `workflow_result`，dataset 汇总报告因此可以引用单任务报告或
完整工作流报告。

`WorkflowDefinition` 用有序 `task_files` 描述子任务，并提供共享参数定义和可选
`cleanup_task`。`load_workflow` 在返回前解析全部相对路径、验证文件存在、拒绝
解析后重复的任务路径，并完成参数默认值与覆盖值校验。`WorkflowRunner` 在桌面
操作前预检所有子任务的必需参数，只向每个子任务传递其声明过的共享参数。主任务
失败后停止后续任务，但 cleanup task 仍会执行。`WorkflowResult` 保存每个子任务
的路径、阶段、参数、状态、耗时和嵌套任务报告。`WorkflowReportWriter` 原子写入
工作流级 JSON 报告，并使用安全文件名和数字后缀避免覆盖既有报告。
