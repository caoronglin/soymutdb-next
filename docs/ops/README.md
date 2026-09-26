# SoyMutDB 运维与 Admin 手册

本目录面向单管理员 Web Admin 和发布值班人员。主链为：对象上传 → 校验 → 入库 → Release 组装 →
ready 检查 → 原子发布或回滚；就绪后可选将静态门户不可变发布到 local / github_pages / cloudflare_pages
目标（见 `data-import-and-release.md` 的「静态发布」一节）。后端状态机、审计和 OpenAPI 契约是权威来源。

详见 [`data-import-and-release.md`](data-import-and-release.md)。生产入口为
[`../../deploy/scripts/upgrade.sh`](../../deploy/scripts/upgrade.sh)，健康检查为
[`../../deploy/scripts/healthcheck.sh`](../../deploy/scripts/healthcheck.sh)。

发布/回滚必须填写理由并留审计；生产镜像使用显式 tag。`gwas` 是 GWAS bucket，`analyses` 是分析对象
bucket，`analyses` 队列由 `worker-analyses` 消费，三者不可混用。

## 核心功能部署（JBrowse 可选）

`core` profile 提供数据库产品的核心：搜索、实体详情、下载与内容。基因组浏览器、BLAST、
按需分析与 MCP 是可选 profile，核心部署不启动它们。门户可用 `VITE_JBROWSE_ENABLED=0`
构建为无浏览器版本（隐藏入口并把 `/browser`、`/gbrowse` 落到说明页）；Pages 制品可用
`SOYMUTDB_JBROWSE_ENABLED=0` 省略 jbrowse 子应用并以 `.no-jbrowse` 标记声明。
见 [`core-only-deployment.md`](core-only-deployment.md)。

## CNB 启动与验收

在 CNB 上「起得来」与「收不收」是两条独立入口：分支页的云原生开发按钮启动可运行环境
（进入即门户预览），`web_trigger_acceptance` / `pnpm accept` 给出分层验收判定与验收清单。
配置、端口约定、验收清单字段与两种分层姿态的区别见
[`cnb-startup-acceptance.md`](cnb-startup-acceptance.md)。
