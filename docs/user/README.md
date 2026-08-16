# SoyMutDB 科研用户指南

本指南面向使用 SoyMutDB 门户查询、浏览和下载数据的科研用户。门户入口为
<https://caoronglin.github.io/soymutdb-next/>；Release/version 是查询、下载和引用应记录的版本边界。

## 快速入口

| 任务 | 当前入口 | 成功结果 |
|---|---|---|
| Gene ID | `/genes/<Gene-ID>`（搜索页 `/search/genes`，支持 `?q=` 直达） | 基因摘要、位置、转录本和关联结果 |
| Location | `/search/location`（支持 `?assembly/chromosome/start/end/run`） | 指定 assembly 和区间内的结果 |
| 全局搜索 | `/search` | 本地与外部来源的分组结果 |
| BLAST | `/blast`（`/search/blast` 保留兼容重定向） | 任务状态、命中列表和浏览器链接 |
| Primer 设计 | `/search/primer` | 引物计算 + 序列提取联动 |
| 序列提取 | `/tools/seqfetch` | 序列结果和下载入口 |
| JBrowse 2 | `/browser` | 指定 assembly 和区域的轨道视图 |
| 下载 | `/downloads` | 对象、来源、版本和校验信息 |

> 顶部导航为固定五入口：Home / Search / Tools / Latest News / Contact（Latest News → `/news`）。

## Gene ID 与 Location

在 `/genes` 输入完整 Gene ID，确认 assembly、基因名称、染色体位置和 Release 标签，再进入变异、
表达、同源、BLAST 或浏览器视图。无结果时检查大小写、物种和 ID 完整性，再用 `/search?q=<Gene-ID>`。

在 `/search/location` 输入 assembly、染色体和起止坐标。无结果表示当前 Release 没有匹配记录，不等同于
服务故障；输入错误则修正格式后重试。页面 error 请保留 Request ID 并点击 Retry。

## BLAST、Primer 与 JBrowse

`/blast` 提交序列后记录任务 ID 和 Release；完成后检查命中数、identity、coverage 和数据库版本。
无命中时确认序列方向、长度、数据库和 Release；失败时保留任务 ID/Request ID 后 Retry。

引物设计入口为 `/search/primer`（纯前端计算 + 序列提取联动）；序列提取入口为 `/tools/seqfetch`。提交前
确认 assembly、链方向和坐标，下载时保存文件名、Release、来源和 checksum。

`/browser`（或基因详情页的浏览器入口）使用 JBrowse 2，应使用相同 assembly 和 Release。轨道不可用时先
Retry，再确认该 Release 是否包含轨道。JBrowse 2 随门户在同一次 Pages 发布中提供，不应假定为独立版本。

## 全局搜索、下载与引用

`/search` 的结果行指向真实前端路由；缺少 URL 的结果为禁用态。外部搜索可按 NCBI、UniProt、Ensembl、
EBI 分组并显示来源状态；单一来源降级不应阻止本地结果。错误/降级时查看提示并 Retry。

下载和引用至少记录：访问日期、Release/version、assembly、Gene ID 或区间、BLAST 数据库版本、文件名、
checksum、来源，以及外部联邦结果的来源标识。Release 切换后，搜索、API、JBrowse、BLAST 和下载应一致
使用新的 active release，不要混用不同版本结果。
