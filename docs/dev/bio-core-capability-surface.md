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
- `scripts/smoke.sh` `--profile contracts` 的 `tests=(...)` 数组末尾收集两份套件，
  使纯 contracts 层（无 Rust/3.15）也能拦住能力面漂移。
- 接线本身由 `scripts/test_bio_core_capability_surface_wiring.py` 钉住：删调用、
  删收集、删 `--self-test` 都必须转红；该文件只读字节，避开
  `test_ci_job_contracts.py` 这个多 PR 共享热点。

## 不改的

不碰 `apps/web/**`、`openapi.json` / `openapi.d.ts`、`main.py`、
`test_ci_job_contracts.py`、`check_bio_core_capability_parity.py`。判定只读源码，
不改变任何端点行为，不新增运行时依赖。真 wheel / `cargo` / 3.15 / PostgreSQL /
Playwright 的验证仍归各自 CI，本机不代签。

## 复现

```
python3 scripts/check_bio_core_capability_surface.py
python3 scripts/check_bio_core_capability_surface.py --self-test
python3 -m pytest scripts/test_bio_core_capability_surface.py \
                 scripts/test_bio_core_capability_surface_wiring.py -q
```
