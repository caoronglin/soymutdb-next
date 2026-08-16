# SoyMutDB 运维与 Admin 手册

本目录面向单管理员 Web Admin 和发布值班人员。主链为：对象上传 → 校验 → 入库 → Release 组装 →
ready 检查 → 原子发布或回滚；就绪后可选将静态门户不可变发布到 local / github_pages / cloudflare_pages
目标（见 `data-import-and-release.md` 的「静态发布」一节）。后端状态机、审计和 OpenAPI 契约是权威来源。

详见 [`data-import-and-release.md`](data-import-and-release.md)。生产入口为
[`../../deploy/scripts/upgrade.sh`](../../deploy/scripts/upgrade.sh)，健康检查为
[`../../deploy/scripts/healthcheck.sh`](../../deploy/scripts/healthcheck.sh)。

发布/回滚必须填写理由并留审计；生产镜像使用显式 tag。`gwas` 是 GWAS bucket，`analyses` 是分析对象
bucket，`analyses` 队列由 `worker-analyses` 消费，三者不可混用。
