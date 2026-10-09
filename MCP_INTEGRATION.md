# MCP 集成说明

本项目通过麦当劳官方 MCP Server（`mcd-mcp`）获取真实门店、菜单、券与价格数据，
在真实数据之上运行最优化算法。本文档说明实际使用的 Server、Tool、调用流程与业务价值。

## MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 传输方式 | streamable HTTP |
| Endpoint | `https://mcp.mcd.cn` |
| 认证 | `Authorization: Bearer ${MCD_MCP_TOKEN}`（仅环境变量，不落盘、不入参） |

配置示例见 [mcp-config.example.json](./mcp-config.example.json)。

## 使用的 Tool 与用途

| Tool | 用途 | 缓存 TTL |
|---|---|---|
| `query-nearby-stores` | 按经纬度获取附近门店，得到 `storeCode` + `beCode` | 24h |
| `query-meals` | 拉取门店在售餐品列表（优化决策空间） | 1h |
| `query-meal-detail` | 套餐组成与可特调项（建模套餐与单品的替代关系） | 1h |
| `query-store-coupons` | 当前门店+点餐方式下实际可用的券 | 1h |
| `query-my-coupons` | 用户卡包券资产（coupon 模式的输入） | 1h |
| `query-promotions` | 门店满减/满折规则（促销后处理） | 1h |
| `list-nutrition-foods` | 餐品营养数据（nutrition 模式与性价比天梯） | 7d |
| `calculate-price` | **权威验价**：本地方案算出后回传 MCP 精确算价，校验偏差 | 不缓存 |

## 调用流程

```
┌────────────┐   initialize / tools/list    ┌──────────────┐
│ mcoptimizer│ ───────────────────────────▶ │  mcd-mcp     │
│   CLI      │                              │ (mcp.mcd.cn) │
└────────────┘                              └──────────────┘
      │
      │ 1. query-nearby-stores(lat, lon)          → storeCode, beCode
      │ 2. query-meals(storeCode, orderType, …)   → 在售餐品 + 价格
      │ 3. query-meal-detail(套餐)                → 套餐组成
      │ 4. query-store-coupons(storeCode, …)      → 可用券
      │ 5. list-nutrition-foods                   → 营养数据
      ▼
┌─────────────────────────────────────────┐
│ 归一化（mcp_adapter）→ pydantic 模型      │
│ 价格统一为「分」，字段别名兼容             │
└─────────────────────────────────────────┘
      │
      │ budget  : 券子集枚举 × 有界背包 DP
      │ nutrition: PuLP ILP（营养约束、费用最小）
      │ coupon  : DFS + 分支限界（心愿单最优用券）
      ▼
┌─────────────────────────────────────────┐
│ 候选方案（Top-K）                         │
└─────────────────────────────────────────┘
      │
      │ 6. calculate-price(storeCode, items)      → 权威验价
      ▼
  终端表格 / Markdown 输出（偏差 > 1 分时提示「以门店实际结算为准」）
```

## 容错与降级

- **401/403**：明确提示 token 无效，并引导使用 `--demo`（内置示例数据）体验；
- **网络超时**：指数退避重试 2 次（1s / 3s），仍失败回退到最近一次缓存并告警；
- **缓存**：按工具分 TTL（见上表），缓存文件同时可作为数据快照用于样例维护；
- **tools/list 校验**：连接后即校验所需工具是否存在，缺失时降级提示。

## 业务价值

1. **把点单变成可计算的问题**：在官方真实菜单与价格上做组合优化，而非凭感觉凑单；
2. **真实省钱**：券与促销的组合空间随券数量指数增长，算法自动找到人工难以发现的最优用法，并用 `calculate-price` 官方接口验价闭环；
3. **营养有据**：`list-nutrition-foods` 真实数据支撑「蛋白质 ≥ X、热量 ≤ Y」的约束求解与性价比天梯；
4. **可复现**：所有结论来自官方接口实时数据 + 公开算法，第三方可验证。

## 建模假设（如实声明）

- 券默认同单互斥（`stackable=false`），与多数实际规则一致；可叠加券按标志位自由组合；
- 满减门槛按「折前小计」判定，最终金额以 `calculate-price` 与门店结算为准；
- budget 模式的折扣类券采用「先 DP 后验证」的后处理近似，可能漏掉「为凑门槛多买」的解；
  budget 模式 Top-K 为近似（扰动重解），nutrition 模式 Top-K 为严格第 K 优（integer cut）；
- 本项目为**非官方社区项目**，与麦当劳公司无关，仅供学习研究；餐品信息、价格与供应状态以麦当劳官方渠道实时结果为准。
