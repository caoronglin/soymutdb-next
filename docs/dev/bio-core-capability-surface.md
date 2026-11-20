# 序列引擎：Biopython（默认）与 Rust 内核（可选）

## 为什么换默认引擎

`SOYMUTDB_BIO_ENGINE` 现在默认 `python`，由 `apps/api/app/services/bio_python_engine.py`
提供实现；`rust` 仍可选择，需要 `soymutdb_bio_core` 轮子在场。两者回答同一套函数
面，因此 `bio_core_bridge`、服务层、HTTP 契约与前端都不需要知道自己连着哪一个。

理由：

- Biopython 是这些操作的参考实现，结果与研究者自己写脚本一致；
- 它带 REBASE 酶库、完整 NCBI 密码子表、nearest-neighbour Tm 与建树器，这些不该手写；
- CPython 3.15 有官方轮子，镜像不需要 Rust 工具链。

## 能力差异（由 `/tools/sequence/capabilities` 如实广告）

Rust 内核实现密码表 1 与 9 个程序；Biopython 引擎实现全部 NCBI 密码子表与 15 个程序。
`capabilities` 报告**当前加载引擎**的能力集，客户端据此发现差异，而不是从 404 反推。

新增的 6 个操作：

| 端点 | 实现 |
| --- | --- |
| `POST /tools/sequence/convert` | FASTA / GenBank / EMBL / tabular 互转 |
| `POST /tools/sequence/restriction-sites` | 限制性内切酶切点（REBASE） |
| `POST /tools/sequence/protein-properties` | 分子量、等电点、消光系数、疏水性 |
| `POST /tools/sequence/melting-temp` | 引物 Tm（Wallace / GC / nearest-neighbour） |
| `POST /tools/sequence/multiple-alignment` | 渐进式多序列比对 + 距离矩阵 |
| `POST /tools/sequence/tree` | 邻接树（NJ），Newick 输出 |

## 两条守卫的分工

- `scripts/check_sequence_capabilities_parity.py` 钉**声明基线**：schema 字段默认值
  等于 Rust 常量，`programs` 覆盖每一条在线 POST 路由。默认值刻意保守，运行时由
  已加载引擎覆盖成更宽的能力集。
- `scripts/check_bio_core_capability_parity.py` 钉**数值限值**与 Rust 常量对偶。

两者都保留：静态编辑里"发明一个没有实现的密码表"仍会被抓到（自检用例覆盖）。

# Rust 内核能力面 ↔ `/tools/sequence/capabilities` 对账

## 补的是哪一类漂移

`GET /api/v1/tools/sequence/capabilities` 除了数值限值，还广告两份**能力清单**：

- `programs`：客户端据此判断能调用哪些计算操作（`reverse-complement` / `match` / …）
- `formats`：客户端据此判断 `/tools/sequence/inspect` 接受哪些文件格式

`docs/dev/bio-core-capability-parity.md` 那一刀把数值与标签逐项绑到内核常量，
但它的比较逻辑只访问**两侧都存在的键**。清单类字段不在这个模型里：从
`programs` 删掉 `"kmers"` 之后，Pydantic 仍给出合法响应、`openapi.json` /
`openapi.d.ts` 仍与导出自洽、所有既存门禁照绿——而 `POST /tools/sequence/kmers`
和 Rust `kmer_counts` 绑定都还活着。**API 静默少广告一项自己实现的功能**，
且没有任何一致性检查会响。反过来加一个没有路由的 `phantom` 同样是谎。

本机实测（活 `fb601eb3`，变异后逐项跑）：删 `"kmers"`、删 `"bed"` 后
`check_bio_core_capability_parity.py` PASS、`check_bio_core_wheel.py --static` OK、
`scripts/test_ci_job_contracts.py` 95 passed 全绿。这就是这个守卫要闭掉的形状。

## 判据

`scripts/check_bio_core_capability_surface.py` 只读**已提交源码字节**（无 wheel、
无 Rust 工具链、无 FastAPI import、无 PostgreSQL），能挂在昂贵构建之前：

1. **能力面是推导出来的，不是白名单硬编码**：`programs` 由
   `apps/api/app/api/v1/tools_sequence.py` 的 `@router.post` 声明推出（排除
   `/inspect`），`formats` 由 `apps/api/app/services/format_inspect_service.py`
   的 `fn = {...}` 派发表推出。因此另一条 PR 真加一条路由 + 广告项时守卫保持绿，
   不需要改守卫——`--self-test` 里有一条正向对照专门钉这个性质。
2. 双向集合比对：广告但无实现、实现但未广告、重复项，逐条点名。
3. 派发表的每个值必须是 `packages/bio-core/src/bindings.rs` 里真实导出的
   PyO3 校验器；已知的计算/校验内核函数集合是必须仍在上线的**下界**。
   删掉一个 `add_function` 或把派发指向不存在的函数都会红。
4. 缺字段 / 形状被改写 / 清单为空一律**失败闭合**，绝不读成「没差异」。
5. `--self-test` 11 例：10 条单向变异 + 1 条正向对照，自证「会响」。

## 接线

- `scripts/verify-bio-core.sh`：构建前 `--self-test` + 现树检查；wheel venv 建好
  后跑两份回归套件（那一层才有 pytest）。插入位置在数值 parity 步骤**之前**，
  与在飞 PR 在该文件里的 hunk 不重叠。
- 两份回归套件只由 `verify-bio-core.sh` 的 wheel venv 收集：**不**改
  `scripts/smoke.sh` 的 `tests=(...)` 数组。该数组尾部已有三条在飞 PR 插入守卫，
  再插一处必然产生内容冲突；把它们留在 bio-core 门禁里，覆盖不丢且不必替别的
  PR 排 rebase 顺序。纯 contracts 层因此**不**承担能力面漂移的判定，这一点由
  接线钉住，别照旧文档去 smoke.sh 里找调用。
- 接线本身由 `scripts/test_bio_core_capability_surface_wiring.py` 钉住：删调用、
  删回归套件收集、删 `--self-test` 都必须转红；该文件只读字节，避开
  `test_ci_job_contracts.py` 这个多 PR 共享热点。

## 不改的

不碰 `apps/web/**`、`openapi.json` / `openapi.d.ts`、`main.py`、
`test_ci_job_contracts.py`、`check_bio_core_capability_parity.py`、
`scripts/smoke.sh`。判定只读源码，
不改变任何端点行为，不新增运行时依赖。真 wheel / `cargo` / 3.15 / PostgreSQL /
Playwright 的验证仍归各自 CI，本机不代签。

## 复现

```bash
python3 scripts/check_bio_core_capability_surface.py
python3 scripts/check_bio_core_capability_surface.py --self-test
python3 -m pytest scripts/test_bio_core_capability_surface.py \
                 scripts/test_bio_core_capability_surface_wiring.py -q
```
