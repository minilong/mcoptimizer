# WorkBuddy 开发上下文

本项目（mcoptimizer）全程使用**腾讯 WorkBuddy**完成创意构思、架构设计、编码、
实机联调与发布。以下为开发对话的上下文记录（由 WorkBuddy 会话导出整理）。

## 开发会话概览

| 阶段 | 时间 | 内容 |
|---|---|---|
| 创意与选题 | 2026-10-09 | 分析 mcd-mcp 全部 30+ 工具能力，扫描比赛规则与排行榜竞品（12 个报名项目均为提示词型 Skill），确定「计算型」差异化方向：把点单变成背包/ILP 最优化问题 |
| 架构设计 | 2026-10-09 | 通过 WorkBuddy 计划模式产出实现方案：Python 算法库 + Typer CLI，src 布局，pydantic 模型（价格分单位），demo 免 token 模式作为一等公民 |
| 编码实现 | 2026-10-09 | 由 WorkBuddy 直接编写全部源码：3 个求解器（budget DP / nutrition PuLP ILP / coupon DFS）、MCP 客户端、缓存层、CLI、37 项 pytest 测试 |
| 实机联调 | 2026-10-09 | WorkBuddy 调用真实 mcd-mcp（https://mcp.mcd.cn）完成字段校准：门店→菜单（101 个真实餐品）→ 券→营养 CSV 解析，budget/nutrition/coupon/ladder 全链路真实数据验证通过 |
| 文档与合规 | 2026-10-09 | README、MCP_INTEGRATION.md、mcp-config.example.json、docs/algorithms.md、演示 SVG 生成 |
| 发布 | 2026-10-10 | WorkBuddy 驱动 gh CLI 完成仓库推送、v0.1.0 tag、GitHub Actions CI（pytest + ruff 双矩阵） |

## 对话要点摘录

**用户**：mcd-mcp 连接器都可以提供什么能力？
**WorkBuddy**：枚举 mcd-mcp 全部工具（点餐链路 / 券与促销 / 订单管理 / 积分商城 /
派对活动 / 抽奖 / 账户营养），输出能力地图。

**用户**：我要参加这个活动（M-China/mcd-developer-innovation-challenge），
帮我再思考下制作什么更容易得奖。
**WorkBuddy**：拉取活动规则与实时排行榜，指出「排名 = GitHub Star 数」的传播战本质，
竞品全部为提示词型 Skill，建议做面向开发者的「计算型」项目：
麦门点单最优化引擎（真实数据上的 DP/ILP）。

**用户**：那请以麦门点单最优化引擎制作这个项目。
**WorkBuddy**：（计划模式）产出完整实现方案，经用户确认技术选型
（Python 算法库 + CLI、动态规划 + PuLP、gh CLI 发布、项目名 mcoptimizer）后进入实施。

**WorkBuddy**：（实施）依次完成 M1 脚手架 → M2 数据模型与 demo 链路 → M3 budget
求解器（券子集枚举 × 有界背包 DP，GCD 缩放）→ M4 nutrition 求解器（PuLP ILP，
integer cut 严格 Top-K）→ M5 coupon 求解器（DFS + 分支限界）→ M6 MCP 客户端
实机联调（解决 SDK 2.x API 变更、响应文本内嵌 JSON 解析、Windows 缓存文件名
兼容）→ M7 文档合规物料 → M9 GitHub Actions CI。过程中运行 pytest 37 项测试、
ruff lint，并实际调用 mcd-mcp 拉取上海真实门店数据验证四个命令。

**用户**：已建好（GitHub 仓库）。
**WorkBuddy**：完成 main 分支推送、v0.1.0 tag，恢复 CI 工作流推送，
报名 Issue 文案交付用户发布。

## 开发工具与环境

- 智能体平台：腾讯 WorkBuddy（计划模式 + Agent 模式）
- 连接器：mcd-mcp（streamable HTTP, https://mcp.mcd.cn）
- 运行时：WorkBuddy 托管 Python 3.13 独立虚拟环境
- 协作方式：关键决策点（技术形态、求解器、发布方式、项目名）由 WorkBuddy
  提供选项、用户拍板；对外动作（建仓、发 Issue）均先经用户确认。
