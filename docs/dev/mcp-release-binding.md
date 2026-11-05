# MCP 工具 ↔ 发布版本的绑定

## 现状问题

同一批 REST 端点在三处被声明：

| 声明 | 位置 | 谁读它 |
| --- | --- | --- |
| 发布契约 | `packages/api-client/openapi.json`（后端导出） | 生成的 `openapi.d.ts`、前端、`check-contract.sh` |
| 工具清单 | `apps/mcp-server/src/mcp_server/manifest.py` 的 `TOOLS[]` | MCP 注册表、`tests/test_smoke.py` |
| 工具实现 | `apps/mcp-server/src/mcp_server/server.py` 的 `@mcp.tool` | `_api_request` 真正发出的请求 |

`check-contract.sh` 只比对快照与生成的 `.d.ts`，**从不读
`apps/mcp-server/**`**；`apps/mcp-server/tests` 只断言工具名注册与请求形状，
且需要装 MCP 包。于是三处声明可以一起漂，而流水线上没有任何一格看得见。

本轮修的是一处具体漂移，也是这层盲区最贵的一种。

## 真缺陷：发布版本在 MCP 侧无声丢失

`_api_request` 原本发送固定头集合（`Accept` + bearer），不发
`X-SoyMutDB-Release`。而这三个公开操作把该头定义为可选参数，并在
`get_release_context()` 里解析它：

- `GET /api/v1/genes/{gene_id}`
- `GET /api/v1/variants/region`
- `GET /api/v1/stats/dashboard`

不带头时的语义是「**请求被服务时正在生效的那个发布**」。后果不是报错，是
静默错答：

- 内部预览窗口里，web 端按已发布 release 读数，MCP 端读草稿 release ——
  同名工具、不同生物学结论；
- 调用方无从知道答案按哪个 release 算出来，因为响应里没有一个字段说明。

这正是 `AGENTS.md` 把「发布感知的查询」与「MCP 授权契约」同时列为必查面的
原因：声明了 release 却没有绑定，比没声明更难查。

## 修法

`release_id` 走**单一传输层**：`_api_request(..., release_id=...)` 把它交给
`_headers(release_id)`，由后者写入 `X-SoyMutDB-Release`。三个作用域内的工具
各自暴露 `release_id` 输入并转发。**不在 per-tool 调用点散着加头** ——
一处决定，一处审计。

不绑的是两处，理由各自记在守卫里，不是漏登记：

- `seqfetch`：`{assembly, genes|region}` 已用显式装配定界，响应也回显该
  装配；再叠一个 release 头等于给一个请求挂两个作用域且不区分。
- `blast_submit`：创建的是作业，release 在 worker 执行时解析；让客户端选
  release 会让一个提交活得比它被钉住的 release 更久。

第三处不绑的理由与前两处不同：`news_list` 与 `analyses_query` 的**操作本身
不发布**该头，给它们加 `release_id` 输入会变成静默空转 —— 调用方以为钉住了
版本，API 一个字节都没收到。守卫对「未发布却带输入」同样报错。

## 守卫

`scripts/check_mcp_release_binding.py`（stdlib-only，读已提交字节）：

1. 工具清单与 `server.py` 的函数集合**双向相等**，且 `@mcp.tool(name=…)`
   与函数名一致（否则清单键与可调用体各自漂）；
2. 每个工具的 endpoint 能解析到**已发布的操作**（方法 + 路径都在快照里）；
3. 操作发布 `X-SoyMutDB-Release` ⇒ 工具必须收 `release_id`；未发布 ⇒ 必须
   不收（白名单不硬编码，新增工具三处一致即放行）；
4. `_api_request` 必须声明 `release_id` 关键字并能把它送到 `_headers`；
5. `_headers` 不得**无条件**写该头 —— 那会把豁免的两个工具一起钉住。

`--self-test` 用六组反向变异证明每条判据都在量东西：传输层停止转发、传输层
不再声明该关键字、`_headers` 抢占、作用域内工具丢输入、作用域外工具凭空加
输入、被注释掉的输入。

`scripts/test_mcp_release_binding_wiring.py` 补守卫自己看不出的那一格：
**守卫被调用了吗**。删 `smoke.sh` 里的调用行、或把本套件从 `tests[]` 摘掉，
都必须是具名 FAIL。

## 改动流程

- 新增 MCP 工具：在 `manifest.py` 的 `TOOLS`、`server.py` 的 `@mcp.tool`、
  以及后端路由三处同步；若对应操作发布 release 头，工具必须收 `release_id`
  并转发给 `_api_request`。
- 后端改路径：`packages/api-client/openapi.json` 需真导出重生成（见
  `docs/dev/openapi` 相关文档），MCP 侧同步改 `endpoint` 与调用点；守卫会在
  两者不一致时点名哪个工具。
- 新增豁免：先写清理由（作用域替代、作业语义、操作未发布），再进
  `ASSEMBLY_SCOPED` / `JOB_CREATED`；不要用「暂时先放行」当理由。

## 已知边界

- 守卫只核对**声明之间**的一致性，不验证运行时行为：真发一次带
  `X-SoyMutDB-Release` 的请求需要 API、数据库与已发布 release，本层不提供。
- `seqfetch` 响应里的 `assembly` 取自入参回显，快照的 `SeqFetchResponse`
  没有该字段 —— 属既有差异，不在本守卫的判据内。
- 本层不需要 MCP 包、不需要 Python 3.15、不需要网络。
