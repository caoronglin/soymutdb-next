# 区间重叠：可见性判定必须先于内核可用性

## 症状

`POST /api/v1/tools/intervals/overlap` 对「未发布的装配」或「不存在的染色体」
本应返回 404（发布边界事实），但在编译好的 Rust wheel 缺失时返回 503
（引擎不可用）。两者都是 fail-closed，客户端却会据此做出完全不同的动作：
404 表示「这个装配没发布」，503 表示「稍后重试」。

## 成因

`apps/api/app/services/interval_overlap_service.py::overlap()` 原来第一行就是
`bridge.require()`：wheel 不在就先抛 `ServiceUnavailableError`（503），
装配/染色体的两次 PostgreSQL 可见性查询根本走不到。

配套测试 `test_unpublished_assembly_fails_closed` 断言 404，但**没有 wheel 时
永远到不了那条断言**。这是「源码与测试一起退化」的另一种形态：不是测试被删短，
而是被测分支被前置条件截断，测试恒红、或只能靠手工 stub 才绿。
`check-contract.sh` 读不到 service 层，`test_openapi_snapshot_contract.py` 也不读。

## 判据

- 可见性（assembly / chromosome / release）是 PostgreSQL 对已发布
  `ReleaseContext` 的判定，与内核是否在场**无关**；
- 内核只在可见性全部通过之后才需要；
- 因此 `bridge.require()` 必须出现在**两次** `NotFoundError` 之后，
  不是「第一个之后」——只挪一半，chromosome 的 404 仍会被 503 盖住。

## 修法与守卫

- `overlap()` 把 `bridge.require()` 移到两次可见性判定之后。
- `apps/api/tests/test_interval_overlap.py` 新增两条回归：把 `require()` 顶成
  「必定抛 503」的桩，仍断言 404，并断言 DB 查询次数（1 / 2）证明判定在前。
  这样没有 wheel 的环境也能证到 404，而不是靠 stub 放行。
- `scripts/check_interval_visibility_order.py` 用 AST 读提交的源码字节，
  要求 `require()` 在两个 `NotFoundError` 之后，且回归用例与次序断言都在。
  它不 import API 包（本机无 3.15 / wheel 也能跑）。
- `scripts/test_interval_visibility_order.py` 用合成树证明 5 类退化
  （require 最前 / 夹在两次判定中间 / 缺 require / 删回归用例 / 删次序断言）
  各自真的会红，并断言守卫与消融套件都登记在 `smoke.sh` contracts 层。
- 接线：`scripts/smoke.sh --profile contracts` 同时跑 live-source 守卫与消融套件。
  读字节的守卫只在它自己跑得到的那条流水线上算数，所以要落在 PR 门禁里。

## 与快照/OpenAPI 的关系

`openapi.json` 目前对 `/tools/intervals/overlap` 只声明 `200/422/500`，
404/503 是运行时域错误信封（`ErrorResponse`）发出的，没有逐路由声明。
本 phase 不动响应声明：那属于另一条正在进行的契约收口（PR #103），
避免两份改动撞在 `tools_intervals.py` 上。这里只保证「运行时真的会发的
那个状态码是 404，不是 503」；声明层随后由那一条补齐。
