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

持久化任务队列：

```text
QueueJob
  -> SQLiteQueueStore
  -> 应用/动作权限白名单
  -> Worker 标签匹配
  -> GUI 任务全局串行 / parallel_safe 任务可并发
  -> 按 priority/created_at 原子领取
  -> RUNNING
  -> PASSED / FAILED / TIMED_OUT / CANCELLED
```

队列执行：

```text
QueueWorker
  -> 恢复超过租约的 RUNNING 任务
  -> claim_next(worker_id)
  -> 后台 heartbeat 续租
  -> 注入式 execute_job
  -> TaskResult 或 WorkflowResult
  -> 校验 worker_id 后写回终态
```

长驻 Worker：

```text
queue worker
  -> 注册并持续在线
  -> 有 Job 时 claim/execute
  -> 空闲时 heartbeat IDLE + poll delay
  -> SIGINT/SIGTERM 停止领取
  -> 当前 Job 完成后标记 Worker offline
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `soc_agent/task_models.py` | 任务、数据源、工作流定义和执行结果的 Pydantic 模型 |
| `soc_agent/runner.py` | 步骤编排、超时、确认、截图和结果记录 |
| `soc_agent/actions/executor.py` | 将确定性步骤分发给环境适配器 |
| `soc_agent/environments/macos.py` | 封装应用、键鼠、截图和等待操作 |
| `soc_agent/accessibility.py` | 遍历 macOS Accessibility 树并归一化控件坐标 |
| `soc_agent/providers/qwen.py` | 调用 Qwen 完成截图验证 |
| `soc_agent/privacy.py` | 在上传和归档前对截图敏感区域进行遮罩 |
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
| `soc_agent/queue_models.py` | 队列任务、生命周期状态和参数数据模型 |
| `soc_agent/queue_backend.py` | QueueStore 抽象接口和后端工厂 |
| `soc_agent/queue_migrations.py` | SQLite 版本化、幂等 schema 迁移 |
| `soc_agent/postgres_queue_store.py` | PostgreSQL 队列、锁和迁移实现 |
| `soc_agent/queue_store.py` | SQLite 持久化、优先级、原子领取和 Worker 注册表 |
| `soc_agent/queue_worker.py` | 领取队列任务、执行并持久化终态 |
| `soc_agent/console.py` | 本地运行控制台、运行历史和进程组取消 |
| `soc_agent/evidence_bundle.py` | 运行证据 ZIP、SHA-256 清单和原子归档 |
| `soc_agent/reviews.py` | 人工复核数据模型、持久化和汇总 |
| `soc_agent/review_workflow.py` | 将复核结论同步到 JSON、HTML、XLSX 和证据包 |
| `soc_agent/cli.py` | 参数解析、依赖装配和 queue CLI |
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
- `click_element`：按 macOS Accessibility 控件属性定位并点击中心
- `read_element`：从 Accessibility 控件读取 title、description 或 value
- `wait`：等待指定时间
- `verify_vision`：截图并请求 Qwen 判断
- `done`：标记任务完成

`verify_vision` 支持期望布尔结果、最多 5 次验证尝试和可配置重试间隔。
数据集 case 可选择对失败结果重试，取消和超时结果不会自动重试。
普通步骤可以配置视觉 `condition`。条件未命中时按跳过处理，条件验证异常时
任务失败，从而区分“业务不适用”和“判断过程本身出错”。
条件还支持 `type: value`，可对运行时变量执行相等、包含、正则和存在性判断；
来自 `sensitive_output` 的实际变量值不会写入条件报告。
条件诊断保存在 `StepResult` 的 `condition_*` 字段中，条件截图使用独立 artifact
文件名，避免覆盖普通视觉验证截图。
确定性动作可配置 `loop.count` 和 `loop.delay_seconds`。循环结果记录配置次数、
实际完成次数和间隔；`verify_vision`、`done` 不允许配置循环。
任务可按 `setup_steps → steps → cleanup_steps` 三阶段执行。每个
`StepResult.phase` 标识所属阶段；cleanup 在主流程结束或失败后都会执行。
审批节点的 `approval_prompt` 和 `approval_result` 会写入步骤报告；审批文本与
普通动作节点一样支持 `${参数}` 渲染。
任务可通过归一化 `redaction_regions` 指定敏感区域。截图先写入同目录临时文件，
完成黑色遮罩后才替换最终文件；遮罩失败会删除临时原图，避免未脱敏截图上传给
视觉模型或进入报告 artifact。
`click_element` 在点击前查找 role、text、title、description 和 value 匹配的
控件；`text` 可匹配 title、description 或 value 任一字段。随后使用控件 frame
中心计算归一化坐标，避免窗口移动后固定坐标失效。
`read_element` 复用同一控件查找器，将提取值和 output 变量名写入
`StepResult`。`sensitive_output=true` 时只记录变量名，不在报告中持久化提取值。
TaskRunner 为每个 Task 维护运行时变量表，并在每个步骤执行前动态渲染
`${output}` 占位符；未声明、重复或与参数冲突的 output 名会被拒绝。
WorkflowRunner 在同一 Workflow 的子任务之间合并
`TaskResult.runtime_values`，并把来源任务和敏感状态记录到
`WorkflowResult.runtime_variables`。敏感变量的实际值只保留在内存上下文中，
不进入持久化报告。

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

队列任务在领取时记录 `claimed_at` 并增加 `attempts`。Worker 启动时会回收超过
租约时间的 `running` 任务：未达到最大尝试次数的任务回到 `pending`，达到上限的
任务标记为 `failed`；`recovery_count` 保留恢复次数。旧版 SQLite 表会在初始化
时自动增加这些列，无需删除已有队列数据库。

任务执行返回 `failed` 或 `timed_out` 且尚未达到最大尝试次数时，Worker 通过
QueueStore 原子接口将任务重新排队，保留上次错误和报告路径并清除本次领取信息。
任务被重新领取时 `attempts` 再次递增；达到上限后写入最终状态。
`cancelled` 表示安全策略或人工拒绝，不会自动重试。

运营人员可以取消 `pending` Job，或在 Job 进入 `failed`、`timed_out`、
`cancelled` 终态后手动重试。取消运行中 Job 不提供“假成功”语义，避免界面操作
仍在执行时提前标记为已停止；当前安全边界是等 Worker 完成或通过 Worker 生命周期
控制停止。手动重试会清除上次领取、报告和错误信息，并把自动重试次数重置为零。

每个 QueueJob 可持久化 `ExecutionPermissions`：`allowed_apps` 和
`allowed_actions`。Worker 执行 Task 或 Workflow 时将其转换为 SafetyPolicy，
每一步在执行前检查动作类型和应用名称；越权命令会产生 `cancelled` 结果，不会
接触未授权的桌面应用。

QueueWorker 领取任务时写入唯一 `worker_id`，执行期间以
`heartbeat_interval_seconds` 后台刷新租约。heartbeat 和 complete 都校验
worker 所有权，旧 Worker 无法覆盖已经被恢复或重新领取的任务。CLI 可用
`--worker-id` 指定稳定的 Runner 标识。

`queue_workers` 表记录 Worker 的主机名、PID、运行状态、当前 Job、启动时间、
最后心跳和离线时间。`queue workers` 命令可按最近心跳窗口查询活跃 Worker，
为后续多机器调度和运行监控提供基础。

`queue worker` 为长驻模式：队列为空时不退出，而是以 IDLE 状态持续心跳和轮询。
收到 SIGINT/SIGTERM 后不再领取新任务，等待当前执行批次完成后注销退出。

CLI、QueueWorker 只依赖 `QueueStore` 抽象接口，具体实例由
`create_queue_store()` 根据路径或 URL 创建。SQLite schema 由
`queue_schema_migrations` 记录版本并按顺序幂等执行，升级已有数据库无需删除。
后续接入 PostgreSQL 时可实现同一接口，而无需修改 Worker 和 CLI 调度逻辑。

PostgreSQL 后端使用 `FOR UPDATE SKIP LOCKED` 原子领取兼容标签的 Job，并使用
`queue_exclusive_locks` 独占记录保护非 `parallel_safe` 的 GUI 任务。Job、
Worker、标签、权限、并发、心跳和迁移字段与 SQLite 后端保持一致。真实
PostgreSQL 集成测试需要在配置数据库服务后执行。

QueueJob 的 `required_labels` 必须全部包含在 Worker `labels` 中才会被领取；
标签比较大小写不敏感。无标签任务可由任意 Worker 执行，标签不匹配的高优先级
任务会保持 pending，并允许 Worker 继续领取下一个可匹配任务。

QueueJob 默认 `parallel_safe=false`。SQLite 领取事务会检查全局是否存在正在运行
的非并行安全任务；存在时只允许继续领取显式 `parallel_safe=true` 的 Job。
Worker `max_concurrency` 只提供并行槽位，不会绕过 GUI 全局串行约束。

## 运行诊断

`soc-agent doctor` 使用只读探针检查 Python、macOS 版本、模型配置、Aqua GUI
会话、Accessibility、Screen Recording、报告目录、QueueStore 和 Worker 心跳。
权限检查调用 macOS 的进程级 preflight API，不触发桌面操作。指定
`--worker-id` 时，该 Worker 必须位于在线窗口内；未指定 Worker 时只产生警告。
命令支持文本和 JSON 输出，只要存在失败项即返回退出码 `1`。

## 业务场景包

`scenarios/` 用目录封装可交付的完整业务场景。`scenario.json` 是严格校验的清单，
引用同目录下的 dataset，并声明所需应用和安全说明。`scenario validate` 只解析
清单、dataset、CSV 和 Workflow 路径，不访问桌面；`scenario run` 复用 DatasetRunner
执行每条 CSV case，并生成 task、workflow、dataset 三级报告。

场景 package 必须使用 workflow target，避免把缺少跨应用编排的单任务包装成完整
业务场景。示例 `customer_followup` 使用虚构客户数据，执行 TextEdit 回访录入、
视觉验证、无保存清理、Calculator 金额核对和批量汇总。

## 对账核心

`soc_agent.reconciliation` 将业务比较与浏览器或视觉数据采集解耦。输入行按
`invoice_id` 对齐，金额使用 `Decimal` 和可配置绝对误差，结果稳定排序并分为
`matched`、`amount_mismatch`、`currency_mismatch`、`status_mismatch`、
`missing_in_erp`、`duplicate_in_erp` 和 `invalid_input`。

`soc-agent reconcile` 不读取模型凭证、不访问桌面。CSV/JSON 对账结果可输出为
文本或 JSON 报告，`--fail-on-differences` 可将任何业务差异转换为 CI 非零退出码。
后续 Browser Adapter 只负责从 ERP 页面采集结构化字段，不复制金额比较规则。
预期输入加载器根据文件后缀选择 CSV 或 openpyxl XLSX 解析，并把日期单元格统一为
ISO 文本，之后进入同一对账与检查点流程。

`soc-agent mock-erp` 使用标准库 HTTP Server 提供本地浏览器夹具。页面通过结构化
`data-testid` 和 `data-field` 暴露搜索框、记录容器和发票字段，并由后端 API 驱动
重复记录、缺失记录等场景。它不依赖真实账号、外部网络或前端构建工具，可通过
固定 JSON fixture 在测试和演示中重复启动。

企业模式在兼容基础夹具的基础上增加 Cookie 会话、登录、退出、分页、CSV 下载和
可控故障。浏览器命令优先使用 `SOC_ERP_USERNAME` / `SOC_ERP_PASSWORD`，显式密码
只用于本地演示。故障配置支持逐票慢响应和一次性 5xx，帮助验证查询重试、错误诊断
和会话恢复。

`soc_agent.browser` 提供 DOM 优先的 Browser Adapter。`MockERPAdapter` 通过
Playwright 打开页面、填写搜索框、等待结果状态，并用 `data-field` 一次性读取
所有结构化字段。缺失记录返回空结果，多条记录保留完整数组供重复检测；截图与
结构化结果写入同一采集结果。当前使用本机 Chrome/Chromium，不依赖视觉模型。
选择器由 `ERPSelectors` 数据对象描述，可从 JSON 档案加载并严格拒绝未知字段，
便于不同 ERP 页面使用独立配置。

`soc_agent.erp_reconciliation` 把 CSV 中唯一发票号逐条交给 Browser Adapter，
汇总页面记录后调用确定性对账核心。批量报告同时保存每张发票的查询结果、记录数、
是否重复、证据截图和采集错误。浏览器只承担数据采集，金额、币种和状态规则仍由
纯逻辑模块负责，因此可以用 JSON fixture 和真实 Chrome 两条路径得到相同结果。

`ReconciliationHTMLReportWriter` 将批量结果渲染为无需前端构建的单文件 HTML，
包含汇总卡片、状态筛选、文本搜索、差异表格、采集错误和相对路径截图链接。HTML
只负责展示，不参与对账判断；所有字段均进行 HTML 转义。

Browser Adapter 支持有限次数重试和重试间隔。最终失败会为当前发票保存失败截图和
文本诊断，但不会中止其他发票。ERP 批量检查点使用预期 CSV 的 SHA-256 作为批次
标识，每张成功发票查询后立即原子写入记录、证据和重试信息。再次执行时只访问尚未
成功的发票；CSV 发生变化时拒绝复用旧检查点，避免混淆不同批次的数据。
检查点同时保存 reconciliation config 的 SHA-256，字段映射、别名或金额容差变化
后不会误用旧缓存。

场景清单支持 `workflow_dataset` 和 `browser_reconciliation` 两种类型。浏览器
场景声明预期输入、ERP fixture 和选择器档案，`scenario validate/run` 会复用同一
浏览器对账链路，不依赖模型 API Key。

`ReconciliationConfig` 将供应商列名映射到规范字段，并对状态与币种执行显式别名
归一化。`ReconciliationXLSXWriter` 生成 Summary、Results、Collection 三个工作表，
包含筛选、冻结表头、截图超链接和重试/缓存信息。
