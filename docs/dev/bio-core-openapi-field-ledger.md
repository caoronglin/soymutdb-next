# OpenAPI ↔ Pydantic ↔ 内核字段台账（R2 阶段文档）

> 状态：**R2 阶段文档 + 判据**。本文只做对账与判定，不代表任何端点行为已改变。
> 基线：`main@05a1d4bb`（2026 现场三次读取一致）。
> 上位规格：`docs/dev/rust-core-development-spec-2026-11-05.md` §7（公共 REST 契约）、
> §12.4（API + OpenAPI + 客户端契约）。

## 1. 本阶段要闭的是哪一类漂移

`GET /api/v1/tools/sequence/capabilities` 除了数值限值，还对外广告一份
`programs` 清单，客户端据此判断「能调用哪些计算操作」。这份清单**声称**是
spec §7.1 端点表的摘要。

现有的三层检查各自都看不见它：

| 检查 | 比的是 | 为什么漏 |
| --- | --- | --- |
| `scripts/check-contract.sh` | `app.main:app` 导出 ↔ `openapi.json` | 两侧同源 Python，一起错的时候互相背书 |
| `check_bio_core_capability_parity.py` | 五个数值上限、`k_range`、`genetic_codes`、坐标系标签 | 只比**常量**，不比清单内容与响应字段 |
| `check_bio_core_capability_surface.py` | `programs` ↔ `@router.post` 装饰器 | 派生自**路由**，因此继承了路由自己的视角 |

于是本刀把第四类东西绑起来：**每个端点的响应字段，追到内核真正吐出它的那个键**。

```
OpenAPI 响应 schema  ==  Pydantic 响应模型  ==  内核 dict 键
```

`engine` 全程跳过：它是服务从 bridge 实时状态填的实现身份，不是从内核结果里拷的值。

## 2. 现场账（本刀判定成立的两条）

守卫在 `main@05a1d4bb` 上跑出的差异**只有两条**，其余 9 个端点 × 每个字段全绿。

### 2.1 `programs` 与 `openapi.json` 实际服务的路径不闭合

`apps/api/app/schemas/sequence_tools.py` 的 `programs` 默认值：

```
reverse-complement  match  align  stats  orfs  translate  kmers
```

`packages/api-client/openapi.json` 里 `/api/v1/tools/` 下**非 GET** 的路径：

```
tools/sequence/reverse-complement   tools/sequence/match    tools/sequence/align
tools/sequence/stats                tools/sequence/orfs     tools/sequence/translate
tools/sequence/kmers                tools/sequence/inspect
tools/intervals/overlap
```

先把已经**证伪**的猜想记下来，免得再被复述：我一度以为 `programs` 把路径段与动词
（`align` / `stats` / `orfs` / `translate`）混用了。按 `openapi.json` 逐段核对，**七个
标签全部命中真实路径段**，这条猜想不成立，不是缺陷，不进台账。

真实缺口只有两条，都在 `/tools/sequence/`、`/tools/intervals/` 前缀之内：

| 缺口 | 事实 | 客户端后果 |
| --- | --- | --- |
| `/tools/intervals/overlap` 不在 `programs` | 该端点由**独立 service** 提供，从未进入 `tools_sequence.py` 的 `@router.post` 列表 | 枚举 `programs` 的客户端**发现不了**一个 spec §7.1 列明的端点 |
| `/tools/sequence/inspect` 不在 `programs` | 路由、schema、`openapi.json`、`format_inspect_service` 派发表四者都在 | 格式校验端点只能靠读 `formats` 猜，`programs` 说没有 |

两条形状相同：**端点被服务、被 schema 化、被导进 `openapi.json`，但没进 `programs`**。
而 surface 守卫的 `programs` 侧派生自 `@router.post`：`overlap` 服务在另一个 module，
`inspect` 则在 `check_bio_core_capability_surface.py::route_programs()` 里被
`if p.lstrip("/") != "inspect"` 一行显式排除（当格式端点处理）。于是守卫对这两条天然哑。
**不把这一行读成错误**：`inspect` 由 `formats` 清单描述、`overlap` 有独立的
`/tools/intervals` 命名空间，两者是否该进 `programs` 是一个产品口径问题，
本刀只把「清单与文档不闭合」这件事钉住，不改口径——见第 5 节。

### 2.2 逐字段追值：全绿，但此前无人证明

9 个端点、5 个响应模型、4 个嵌套条目模型逐字段追到 PyO3 `set_item` 键，结论是
**没有一处「Python 凭空造值」**。这件事此前是无人验证的空白，现在成了守卫：

- `SequenceStatsResponse(**raw)` / `TranslateResponse(**raw, engine=…)` 这类整字典解包：
  内核改一个键名 → 请求时 `KeyError`，静态检查看不见；
- `raw["k"]` 这类显式读取：绑定少吐一个键 → 同样是 `KeyError`，只是挪了一层；
- 反过来，响应模型多一个字段而内核没有对应键 → 服务只能自己编。

三类现在都会点名。**「Python 拥有该字段」必须写在
`check_bio_core_openapi_fields.py` 的 `PYTHON_OWNED` 表里并给出理由**，理由为空也算红。

## 3. 判据（`scripts/check_bio_core_openapi_fields.py`）

只读已提交字节：`packages/api-client/openapi.json`、`apps/api/app/schemas/sequence_tools.py`、
两个 service、`packages/bio-core/src/bindings.rs`。不需要 wheel、`cargo`、FastAPI
import、PostgreSQL，因此能挂在 `maturin build` **之前**。

1. **`programs` 按文档校验**：与 `openapi.json` 里 `/tools/sequence/`、`/tools/intervals/`
   下非 GET 路径双向闭合，缺一个、多一个、出现没有路径的标签都点名。
   范围只认这两个前缀——`/tools/seqfetch`、`/tools/ld`、`/tools/enrichment` 等既有
   router 不在 spec §7.1 的范围内，把它们算进来会把一张诚实的清单变成新的谎。
2. **逐端点三方比对**：OpenAPI 响应 schema 名 == Pydantic 模型名；两侧字段集合相等。
3. **每个非 Python-owned 字段必须有内核键**，按 `bindings.rs` 的 `set_item` /
   共享 `hit_dict` / `overlap_intervals` 的按区域 dict 取键。
4. **显式读取者单独过一遍**：`_call("<binding>"…)` 所在函数体内的 `raw["x"]`，
   内核不吐 `x` 就点名。
5. **嵌套条目模型同样处理**：`MatchHit` / `OrfCandidate` / `KmerItem` / `OverlapQueryResult`。
   `KmerItem` 在 FFI 上是 `(kmer, count)` 元组，不是 dict，所以它的两个名字是唯一可能。
6. 空集合一律**失败闭合**，不读成「没差异」。
7. `--self-test` 9 例单向变异，逐条证明会响。

### 3.1 台账基线不是白名单

`KNOWN_DRIFT` 按**值 + 原文**钉住今天的这两条，并且**双向断言**：

- 现场跑出新的一条 → 红（新漂移藏不进基线）；
- 把其中一条修掉 → 红（基线条目没跟着删，说明台账在说谎）。

这是「承认债，但不让债变成免检区」的写法。修 `programs` 的那一刀必须同时删掉
对应基线条目，否则本守卫自己会拦住它。

## 4. 接线

- `scripts/verify-bio-core.sh`：`--self-test` + 现树检查排在
  `step "Rust kernel ↔ advertised capability surface"` **之前**（都在昂贵构建之前）；
  回归套件由 wheel venv 收集（那一层才有 pytest）。
- **不动** `scripts/smoke.sh` 的 `tests=(...)` 数组：三条在飞 PR 已往同一个尾部插入，
  再插一处必然产生内容冲突，而覆盖并不因此增加。
- **不动** `test_ci_job_contracts.py`（多 PR 共享热点）。接线由
  `scripts/test_bio_core_openapi_fields_wiring.py` 单独钉：删调用、删回归收集、
  往 `smoke.sh` 里塞调用都必须转红。

## 5. 本刀不改的

不碰 `apps/web/**`、`apps/admin/**`、`openapi.json` / `openapi.d.ts` 快照、
`test_ci_job_contracts.py`、其他两份 bio-core 守卫，也不改任何端点行为。
**`programs` 到底要不要补 `inspect` / `intervals/overlap`、标签口径统一到路径段还是
动词，是带 OpenAPI 快照改动的独立一刀**（重新生成 `openapi.json` + `openapi.d.ts`
+ 前端消费点），留给下一个 phase PR，本刀只负责让差异无法再静默存在。

## 6. 复现

```
python3 scripts/check_bio_core_openapi_fields.py --self-test
python3 scripts/check_bio_core_openapi_fields.py
python3 -m pytest scripts/test_bio_core_openapi_fields.py \
                 scripts/test_bio_core_openapi_fields_wiring.py -q
```

本机能力面：CPython 3.11.2 / pytest 9.2.0（仓外安装）/ Node 26.13.0 / pnpm 12.11.2；
**无 cargo、无 cc、无 CPython 3.15**，因此 `cargo fmt/clippy/test`、maturin wheel、
真实 wheel import smoke、全量 API·worker pytest 均**未在本机运行**，以 CI 终态为准。
