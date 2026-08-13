# SoyMutDB 数据发布主链与搜索信息架构设计规格

- 状态：approved，2026-08-13
- 前身：本会话 5 条只读审计（Admin / 数据上线 / 搜索 / 旧代码 / UI）+ 四方向交互 Mockup + 逐部分确认

## 1. 背景与范围

五条审计确认当前管理面约一半为装饰页面（前端调用后端不存在的端点，靠空表兜底）；VCF/GFF3/FASTA/BLAST-DB/Seed 导入为静默 no-op；worker 三个 ingest 任务是孤儿代码且 gff3/品系为空壳；Release 行无处创建；JBrowse 构建了但从未发布；`analyses` 队列无消费者；全局搜索结果链接指向 `#`。

本规格交付一条可工作的「数据导入 → Release → 发布/回滚」主链，同步修复搜索契约、Admin 装饰页面与关键页面状态，清理确认无消费者的旧代码，并补齐科研用户 / 运维 / 开发者三套文档与部署调整。

### 已确认决策

- 首批支持全部 7 类导入：FASTA、GFF3、VCF、BLAST DB、Seed、Expression、Homolog
- Admin 仅 Web：移除 Tauri/Rust IPC 与 Windows 打包链
- 单管理员审批（暂不考虑多人）；发布/回滚需确认、理由与审计
- 无历史数据：直接初始化，不做兼容回填或双写迁移
- Release 原子切换：门户搜索、API、JBrowse、BLAST、下载一次性切换，任一组件未就绪则不发布
- 外部联邦搜索（NCBI/UniProt/Ensembl/EBI）本轮接入前端而非删除
- 本轮删除 `apps/core-rs`、`deploy/windows/` 及 Makefile `build-windows` 目标
- UI 采用：搜索 A（全局发现 + 独立工具页）+ Admin A 首页（任务优先）+ Admin B 二级资源骨架
- 文档面向科研用户 + 运维 + 开发者三套

## 2. 目标架构

- 单一 Admin Web（React 19 / TanStack / AntD 6），移除 Tauri 与 Windows 链
- 导入、验证、发布、审计均由后端权威状态机驱动；UI 只渲染与提交操作
- 上传经 MinIO 分片直传；API 只签发预签名会话与登记对象，大文件不穿 FastAPI 内存
- `/api/v1` 向后兼容；新增走 `/api/v1/admin/*` 与等价端点；OpenAPI 为唯一契约来源
- 原子发布只切换 PostgreSQL `active_release` 指针
- 7 类导入统一协议 + 类型适配器；Release 由数据集组合

## 3. 数据模型（PostgreSQL 权威）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `data_sets` | type, release_id?, source_objects, status, validation_evidence | 一次导入 = 一个数据集 |
| `import_tasks` | status, progress, error_detail, idempotency_key | 任务实例与执行状态 |
| `releases` | name, assembly, status, active_at, rolled_back_at, reason | 发布单元 |
| `release_data_sets` | release_id, data_set_id | 组合关系，支撑原子发布 |
| `active_release` | 指针 | 原子切换入口 |
| `provenance` | 文件、校验和、来源、工具与版本 | 导出清单与引用 |
| 审计 | 复用 `AuditLog` | 导入、审批、发布、回滚均结构化记录 |

### 导入状态机

```
uploading → validating → ingesting → ready → published → rolled_back
                  ↘ failed（可重试）       ↘ failed
```

### 发布状态机

```
draft → validated → ready → published → rolled_back
```

- 每个转换服务端校验；UI 只提交 `stage.x.completed`
- 验证失败不能 ingest；数据集未全部 ready 不能发布
- 幂等：`idempotency_key`（如 `import:{id}`），dispatch 与 outbox 原子提交
- 并发：Release 发布加行锁，阻止并发发布冲突

## 4. 导入与发布实现边界

### 上传

- 浏览器分片直传 MinIO；API 签发预签名会话与对象登记
- 7 类导入各自对象目录与校验
- 上传完成置 `uploading`，文件完整后进入 validating

### 7 类适配器（worker 内）

| 类型 | 动作 |
|---|---|
| FASTA | 写 assembly/chromosome，生成索引对象 |
| GFF3 | 写 genes/transcripts/exons/aliases，与 FASTA 一致 |
| VCF | 写 ClickHouse `variant_facts`（Replacing 语义去重），校验 release 与样本 |
| BLAST DB | makeblastdb 派生索引，注册 `blast_databases` |
| Seed | 写 seed 请求/库存表 |
| Expression | 写 expression 表，on_conflict 去重 |
| Homolog | 写 homolog 表，on_conflict 去重 |

- 每个适配器更新 ImportTask 状态与进度；失败保留部分批次标记，可重试

### 原子发布

- 全部数据集 ready 后组装 manifest（版本、来源、校验和、引用）
- 发布：事务内切换 `active_release` 指针 + 写 release/audit；提交后触发 JBrowse bundle 构建与 smoke
- 回滚：回到上一 active release，写理由与审计

## 5. 搜索契约修复与清理

### 契约统一

- `SearchResultItem` 增加 `url`（前端路由，非 API 路径）与 `by_type`
- 消除 `type` vs `types`、`page` vs `limit` 漂移
- 统一游标分页：`cursor/next_cursor/has_more/total_count`；`total_count` 为 null 时前端隐藏总数
- 删除死接口：`getGeneTranscripts/getGeneVariants/getGeneAnnotations/getGeneVariantSummary/getExportStatus/cancelBlastJob`
- 修正 `getGeneExpression` 路径
- 结果整行可点击；缺失 URL 用禁用态而非 `#`
- 重新生成 openapi.json + openapi.d.ts；更新 e2e 选择器并补 `url` 断言

### 外部联邦搜索接入前端

- 复用适配器、电路断路器和缓存
- `/search` 增加“外部来源”开关，聚合结果分组，标注来源与状态
- 增加错误/降级态与来源健康

### Admin 404 与清理

- 删除无后端的 users/variants/assemblies/tracks/seeds/blast/releases 操作装饰页面及侧栏入口，后续按资源目录规范重建
- 统一 `_require_admin` 到共享 helper；dashboard 补权限校验；修复 `role.level>=7` 死代码
- Tier 1：删除 `tauri-api.ts` 与 4 个 Rust 命令、`tracks.ts`/`mutant-lines.ts`/`releases.ts` 死导出、遗留 SSG `search.html`、`filterSearchResults/sortResults`
- Tier 2：删除 `apps/core-rs`、`deploy/windows/`、Makefile `build-windows`
- 重新生成 openapi 契约；`_headers` 转 gh-pages 语义或删除；`analyses` 队列补 worker 或明确下线

## 6. UI 落地

- `/search`：全局发现首页 + 独立工具页，去掉重复入口卡
- Admin：任务优先首页 + 资源目录二级骨架
- 完整状态：loading（保留旧数据）、empty（区分无数据/无匹配）、error（Request ID + Retry）、详情、移动端
- 保持现有科学绿色、HarmonyOS Sans SC、JetBrains Mono、OKLCH token；不引入新组件库
- AntD 负责复杂组件，共享 UI/Tailwind 负责页面框架与结果行；单一页面不混用两套 Card

## 7. 使用文档

- `docs/user/`：科研用户门户指南（Gene ID、Location、BLAST、Primer、GBrowse、全局搜索、下载与引用）
- `docs/ops/`：Admin 数据上线手册（7 类导入、校验、Release 组装、原子发布、回滚、备份恢复、故障排查）
- `docs/dev/`：开发者（架构、状态机、接口契约、幂等与审计、CI 门禁、部署拓扑、清理清单）

## 8. 部署调整

- `docker-compose.yml`：新增 worker-analyses（消费 analyses 队列）或明确下线；minio-init 建 gwas 桶；backup 默认含 gwas
- `upgrade.sh`：修复停栈判定与编号；migrate SQL 入镜像；mcp-server 加镜像 tag；回滚覆盖全服务
- `ci.yml`：镜像 tag 自动推送 + upgrade 预检 `docker manifest inspect`
- `pages.yml`：新增 JBrowse 部署 job（dist-jbrowse → `soymutdb-jbrowse/`）
- `_headers` 转 gh-pages 语义或删除

## 9. 验收标准

- [ ] 7 类导入可上传、校验、入库、失败重试，全程有审计
- [ ] Release 可组装、验证、原子发布与回滚，理由与审计完整
- [ ] 发布后门户搜索、API、JBrowse、BLAST、下载一致切换
- [ ] 全局搜索结果链接有效，联邦搜索前端可用且有降级态
- [ ] Admin 无装饰页面，搜索/表格有完整状态与 URL 状态
- [ ] 三套文档可指导科研用户、运维与开发者完成核心任务
- [ ] 无消费者旧代码清理完成，CI 门禁、契约生成与部署脚本可用
