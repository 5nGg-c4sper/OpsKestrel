# SOC Agent Roadmap

## 产品定位

SOC Agent 是一个面向 macOS 桌面软件的可观测自动化工具。它优先使用确定性操作完成
任务，并将视觉模型用于截图验证和异常恢复，最终输出可审计的执行报告。

目标场景：

- 没有 API 的桌面软件回归测试
- 企业旧系统的批量录入、查询和导出
- 需要人工确认的跨应用办公流程
- 需要截图、步骤耗时和失败原因的质量检查

非目标：

- 无人监管的支付、退款和审批
- 绕过验证码、风控或权限控制
- 第一阶段同时支持多个操作系统
- 用视觉模型替代全部业务规则

## 已完成

- JSON 任务模型与严格字段校验
- 任务参数定义、默认值、`${参数}` 渲染和 CLI 覆盖
- macOS 应用启动、输入、按键、点击、等待和截图
- 确定性动作执行器
- 任务 Runner、超时、人工确认和结果记录
- SiliconFlow Qwen 视觉验证 Provider
- 正向/反向视觉断言和视觉验证重试
- 多应用前台激活动作和跨应用示例任务
- 基于视觉条件的步骤跳过和条件示例任务
- 确定性步骤循环执行、循环结果审计和示例任务
- 任务前准备、任务后清理和阶段审计
- JSON 执行报告和截图 artifact 归档
- 结构化 `failure.log` 归档和报告日志路径引用
- 单任务 CLI
- 批量任务 suite
- 批量任务套件汇总报告和 CLI 报告路径输出
- 数据驱动 dataset 模型、加载器、顺序执行器和汇总报告
- CSV 逐行数据源、参数列映射和加载期校验
- TextEdit 多记录 CSV 工作流及不保存 cleanup
- 业务工作流定义模型、共享参数解析和 cleanup task 契约
- Workflow Loader、相对路径解析和加载期文件校验
- WorkflowRunner 参数预检、顺序执行、失败停止和 cleanup
- Workflow 汇总报告、CLI 命令和双应用示例
- Dataset 的 task/workflow 互斥目标契约
- Dataset Loader 的 task/workflow 目标识别和路径解析
- CSV 逐行执行完整 Workflow 及嵌套 WorkflowResult 汇总
- 确定性关闭文稿动作及无保存 cleanup
- M3 显式操作审批节点及审批结果审计
- M3 截图敏感区域遮罩及失败清理
- M3 SQLite 持久化任务队列、优先级和原子领取
- M3 QueueWorker 顺序执行、异常兜底和终态写回
- M3 队列入队、查询、单次执行和 drain CLI
- M3 stale running job 租约恢复、最大尝试次数和数据库迁移
- M3 队列任务应用/动作权限白名单及执行前隔离
- M3 Worker 唯一身份、后台自动心跳和所有权校验
- M3 Worker 注册表、在线状态和 queue workers 查询
- M3 Worker 能力标签、Job 标签要求和不匹配任务跳过
- M3 Worker 并发槽、parallel-safe Job 和 GUI 全局串行保护
- M3 QueueStore 后端接口、工厂和版本化 SQLite 迁移
- M3 PostgreSQL QueueStore、SKIP LOCKED 领取和跨机器独占 GUI 锁
- PostgreSQL 临时测试环境、真实集成测试和 GitHub CI
- PostgreSQL 双 Worker 并发领取、GUI 锁和跨 Worker 恢复测试
- macOS Accessibility 控件定位模型、查找器和 click_element 动作
- Accessibility read_element 控件值提取与敏感输出报告保护
- Task 内运行时变量渲染和跨应用读取值传递
- Workflow 子任务间运行时值传递及变量来源审计
- 运行时变量 equals/contains/regex/exists 条件判断和诊断
- 长驻 Worker 轮询、空闲心跳和 SIGINT/SIGTERM 优雅退出
- macOS LaunchAgent Worker 安装、异常重启、状态查询和安全 plist 渲染
- M4 Queue 失败/超时自动重试、最终尝试上限和取消任务不重试
- M4 只读运行诊断、权限探针、队列后端和 Worker 在线检查
- M4 待执行任务取消、终态失败任务手动重试和自动重试预算重置
- M5 场景包清单、路径校验、`scenario validate/run` 和客户回访示例
- M5 跨系统发票对账核心、Decimal 金额规则和 `reconcile` CLI
- M5 本地 Mock ERP、稳定 DOM 选择器和可重复发票查询服务
- M5 Playwright Browser Adapter、DOM 字段读取、重复/缺失处理和页面截图
- M5 CSV→浏览器→DOM 对账→逐票截图→批量差异报告端到端编排
- M5 可筛选 HTML 对账报告、汇总卡片、文本搜索和截图证据链接
- M5 ERP 查询重试、失败截图/诊断和单票失败隔离
- M5 CSV 哈希检查点、逐票原子保存和失败项断点续跑
- M5 CSV/XLSX 预期输入、外部选择器档案和浏览器场景清单
- M5 `scenario validate/run` 浏览器对账分发
- M5 字段映射、状态/币种别名、配置指纹和 XLSX 对账工作簿
- M5 企业 Mock ERP 登录、会话、分页、故障注入、CSV 导出和浏览器自动重登录
- M5 PDF 发票解析、500 条压力数据生成和一键故障恢复演示
- M5 本地报告/Worker 控制台、macOS 引导脚本和 CI 对账验收
- 项目总览、五分钟面试脚本、宣传材料、架构图和简历要点
- 本地控制台上传 CSV/XLSX/PDF、实时日志、运行历史和多格式产物下载
- 本地控制台运行取消、进程组清理和 `cancelled` 状态审计
- 运行证据 ZIP、SHA-256 文件清单和 CLI `bundle` 归档命令
- 对账差异人工复核、复核人/备注持久化和多格式报告同步
- 控制台操作员 Token、角色权限和哈希链审计日志
- 历史运行选择、批量复核、复核关闭和内容指纹校验
- 一键启动、健康检查、离线发布自检和发行工作流
- README 实拍控制台、企业 ERP 登录页和 HTML 对账报告截图
- `soc-agent dataset` 数据集命令、失败停止/重试策略和诊断输出
- 基础安全策略
- GitHub Actions 单元测试配置
- 手动触发的自托管 macOS GUI 冒烟工作流

当前验证结果：

- 443 个单元测试通过
- macOS LaunchAgent Worker 已完成真实队列领取、Accessibility 点击、
  键盘输入、截图视觉验证、跨应用 Workflow、报告写入和清理回归
- LaunchAgent Worker 已验证失败任务连续自动重试 3 次并写回最终失败状态
- LaunchAgent Worker 已验证 `SIGKILL` 后自动拉起、恢复过期租约并成功重跑任务
- 客户回访场景包已完成 3 个 CSV case、6 个子任务的真实 macOS 批量回归
- 发票对账核心已覆盖 20 条固定记录、7 类结果和 CI 差异退出码
- 本地 Mock ERP 已验证健康检查、正常发票、重复发票和 404 查询
- Playwright Browser Adapter 已用真实 Chrome 读取重复发票并保存页面截图
- 20 条 CSV 已完成真实 Chrome→DOM→对账→20 张证据截图端到端回归
- HTML 对账报告已验证 20 行数据、状态筛选、搜索和 20 个截图链接
- ERP 批量已用真实 Chrome 验证全量执行后缓存命中 20 条并生成恢复报告
- 浏览器对账场景已通过 `scenario run` 完成 20 次真实 Chrome 查询和 HTML 报告
- 正式场景已验证配置指纹、20 条检查点和三工作表 XLSX 对账报告
- 企业 Mock ERP 已验证登录、会话过期、分页、503 重试、慢响应和 CSV 导出
- 计算器任务连续批量执行成功
- 两组参数化计算器任务在真实 macOS 上验证成功
- 双 case 数据集在真实 macOS 上连续执行成功
- 真实报告包含视觉验证截图

## 下一里程碑

### M1：可靠的单机 QA

- 任务参数化
- 数据驱动测试用例
- 任务重试和失败恢复
- 更完整的视觉断言
- 失败截图和日志归档

### M2：可维护的自动化工作流

- 多应用任务编排
- 条件分支和循环
- 任务前准备与任务后清理
- 批量报告和汇总
- CI 触发真实 macOS Runner

### M3：企业 RPA 基础能力

- 敏感应用和区域遮挡
- 操作审批节点
- 任务队列和调度
- 审计日志与权限隔离
- 多机器执行

## 质量指标

- 单任务成功率不低于 90%
- 失败报告必须包含失败步骤、错误和截图
- 单元测试覆盖所有纯逻辑和策略模块
- 所有高风险动作必须显式确认
- 不允许视觉模型绕过安全策略

## 许可与来源

本项目基于 OthersideAI 的 Self-Operating Computer 二次开发，继续保留原项目
MIT License 和版权声明。
