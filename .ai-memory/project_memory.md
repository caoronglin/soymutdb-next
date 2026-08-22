# Project Memory

## Decision Record: 生产控制面保留 PostgreSQL

**日期**: 2026-08-19
**问题**: PostgreSQL 是否可由 SQLite 替代。

### 选项分析

| 选项 | 优势 | 劣势 | 复杂度 |
| --- | --- | --- | --- |
| 保留 PostgreSQL | 保留行锁、`SKIP LOCKED`、advisory lock、PG 类型、迁移与现有灾备 | 需要独立数据库运维 | 低 |
| 增加 SQLite 轻量 profile | 单机演示部署简单 | 必须单进程并禁用或重写 outbox、发布、导入及并发任务；另建 schema/测试 | 中高 |
| 全面替换 SQLite | 单文件存储 | 重写并发协议、迁移、类型、容器、监控和灾备，无法维持当前多 writer 拓扑 | 高 |

### 决策

**选择**: 生产与完整开发栈继续使用 PostgreSQL；只有明确需要离线单机演示时，才评估独立、功能受限的 SQLite profile。
**理由**: 当前 API/Worker 依赖 PostgreSQL 行锁、`FOR UPDATE SKIP LOCKED`、session advisory lock、JSONB/UUID/INET、原生 enum 和 PostgreSQL Alembic 链；生产同时运行多 API worker 与多个 Celery writer。
**Trade-offs**: 接受 PostgreSQL 的部署和备份运维成本；若目标只是降低运维，优先采用托管 PostgreSQL，而不是更换数据库语义。

### 影响范围

- `apps/api` 数据模型、事务、迁移和 outbox。
- `apps/worker` 导入锁与数据库驱动。
- `docker-compose.yml`、`deploy/scripts`、监控及灾备流程。

### 撤销条件

产品明确收缩为单机、单用户、单写进程，且不需要 Celery 并发、发布/回滚、outbox、导入互斥或生产高可用；同时 SQLite schema、并发反例、备份恢复和完整声明功能集均通过独立验证。
