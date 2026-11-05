# 合并把快照打回旧形状，门禁会替你发现

## 症状

一条 PR 的 head pipeline 全绿，合并进 `main` 之后 `main` 的 push pipeline 立刻红：

```
CONTRACT DEBT: packages/api-client/openapi.json is out of sync with app.main:app.
  changed schemas: AlleleFreqVariant, LdVariant
```

`main` 上真实导出仍然带着 `assembly` 字段（`packages/api-client/openapi.json` 里也有），
所以「代码丢了字段」解释不通 —— 丢的是**生成产物**。

## 成因：合并提交里，快照取了「只有我方改动」的版本

`openapi.json` 与 `openapi.d.ts` 是**生成产物**，内容跟整棵后端树的形状走，不跟某一条 diff 走。
当一条 PR 里手改过快照、而它合并时 base 一侧又恰好改过同一批字节，冲突解决器的
「两边都动过就别猜」会把快照退回成只有本方改动的那一版 —— 于是别的分支对快照的贡献
被静默丢掉，而后端代码（非生成产物，正常三方合并）仍在。头一次 `check:contract` 跑在
`main` 上时才发现。

这类丢失**在 PR 的 head pipeline 上看不见**：那条流水线用的是分支自己的树，两段改动都在。

## 判据（不需要跑后端）

1. 合并后立刻对 `main` 跑一次 `check-contract`，别只看 PR 的绿。
2. 红的时候先分辨是哪一种，别急着重导：
   - 真实导出**没有**这个字段 → 后端改动被合并冲掉了，回去查语义改动。
   - 真实导出**有**这个字段、快照没有 → 只是快照，重导即闭合。
   后者可以用「`main` 之上再 merge 一次本分支的 head，冲突在这几个文件上」来确认成因。

## 修法

一个 commit 里做完三件事，不要拆：

1. 用真实后端导出（`pnpm --filter @soymutdb/api-client generate:api-client`，或导出到自己那棵树后
   与 `main` 的 `openapi.json` 逐字段整形）；
2. 重新生成 `openapi.d.ts`，**不手改**；
3. 重跑 `check-contract` 与 `check:contract` 覆盖的 `scripts/test_openapi_snapshot_contract.py`。

不要手改 `openapi.json`：手改会连同无关 schema 的字节一起漂移（`SettingValue` 被内联、
`paths` 被按字母序重排都这么发生过），而门禁比的是「实时导出 vs 快照」，手改只能靠猜对齐。

## 预防

- 含 schema 可见改动（`required` / `default` / 字段增删）的 PR，把**重导快照**与**语义改动**合并到
  同一个 commit，门禁就没有在合并时替你记账的机会。
- 合并之后跑一次 `main` 的 verify pipeline（push 触发）是这条契约唯一的事后判据；
  绿色 PR + 红色 `main` 正是本文件描述的那种失败。

## 比较基准：两点 diff 与三点 diff 不是一回事

`main` 被 force-rewrite 过之后，`git diff main...HEAD`（三点）会以 **merge-base**
为基线，而 merge-base 可能是旧形状的链头；`git diff main HEAD`（两点）才比两棵树的
真实端点。曾有一处 `title: "Assembly"` 的差异用三点 diff 看着是真回退，换成两点后是
逐字节相同——「逐字节一致」的结论没错，错的是把 merge-base 当成了 `main` 的当前形状。

判据：

- 判定「这条分支相对当前 `main` 改了什么」，默认用两点 `git diff origin/main HEAD`，
  但结论前必须先确认 `merge-base` 是不是 `main` 的祖先（见下节）；
- 三点 `git diff origin/main...HEAD` 只回答「本分支自己提交了什么」，适合看净新增，
  不适合判定是否回退了 `main` 上已有的东西；
- 报结论时带上 `git rev-parse origin/main` 与 `git merge-base origin/main HEAD`，
  否则「main」和「基线」容易被混成同一棵树。

### 反向的坑：stale base 让两点 diff 把「没跟上 main」报成回退

上面那条是三点 diff 拿旧 merge-base 当 `main`，把旧形状看成回退。反过来也成立：
基线是 **stale base** 时，两点 `git diff origin/main HEAD` 会把 `main` 后来前进的部分
整片显示成「本分支删掉了它」。实测一例：

- `origin/main = 93443961`（#116 合入），分支 head `a48ce1d5`，`merge-base = 8bc94028`；
- `8bc94028` 是 `main` 的祖先，分支从未碰过 `scripts/*`；
- 两点 diff 报 `test_ci_job_contracts.py` −134、`verify-backend-tests.sh` 加回
  `sh.rustup.rs` / `maturin build`、`verify-bio-core.sh` 少 `rm -f` —— 三处「删除」全是影子；
- 三点 `git diff 8bc94028 a48ce1d5`：改动 10 个文件，全在 `apps/web/**` 与
  `packages/api-client/src/**`，与 #116 的 12 个文件交集为空；
- 试合并树 `git merge-tree --write-tree 93443961 a48ce1d5` → `0ea233d1`，`rc=0`，
  该树里 #116 的 12 个文件逐 blob 与 `main` 相同，边界守卫（单次建构断言、
  `sh.rustup.rs`/`maturin build` 计数 0、`rm -f …/soymutdb_bio_core-*.whl`）全部在位。

判据补一句：**两点 diff 上看见「删了 `main` 的东西」时，先查 `merge-base`；若
`merge-base` 是 `main` 的祖先、且该分支从未碰过那个文件，那是 stale base，不是 revert。**
分辨办法是把两条 diff 与文件集放一起看：

```bash
git rev-parse origin/main $(git merge-base origin/main HEAD) HEAD   # 三棵树先摆出来
# 本分支真实改动（三点），与两点读数相减的那部分才是「基线滞后」
comm -13 <(git diff --name-only origin/main...HEAD | sort) \
         <(git diff --name-only origin/main HEAD  | sort)
```

`rc=0` 在这里也确实是无损的，但理由不是「没有冲突」，而是**两侧改动的文件集合不相交**，
3-way merge 各自取增量；一旦两侧动过同一批字节，`rc=0` 仍然可能静默丢东西
（见上文生成产物那节）。

## 源码与测试一起退化时，契约门禁不会喊

`check-contract.sh` 比的是「后端实时导出 vs 提交快照」，`test_openapi_snapshot_contract.py`
比的是快照自身的形状。两者都不读 `apps/web/src/**`。一次 stale-base 分支同时带了旧的
`variants` 行键（`?? ""` 拼接）和只剩 2 条的 `row-key.test.tsx`：vitest **绿 2/2**，
没有任何门禁报错——测试跟着代码一起退，绿灯反而更亮。

`scripts/check_variant_row_key_contract.py` 独立读提交的源码与测试文件，要求行键使用
`JSON.stringify([...])`、且回归用例保留「null 与空串分开」「同键同桶」两组；任一缺失即失败。
它挂在 `verify-frontend-artifacts.sh` 与 `smoke.sh --profile contracts` 两层，
`scripts/test_variant_row_key_contract.py` 用合成树证明每个负例真的会红。

行键有两种合法拼法，守卫两种都读：内联 JSX 箭头 `rowKey={(row) => ...}`，以及
具名 `const rowKey = (row) => ...` 配 `rowKey={rowKey}`。PR #99 把注释搬出 JSX
属性区时改成了后者，而守卫当时只读内联形式，于是**行键本身正确、门禁却在活 main
上变红**：`rowKey={rowKey}` 这个引用里并没有 `JSON.stringify`。改守卫而不是改行键
是关键——把具名函数塞回 JSX 只为迁就正则，等于让门禁反过来决定源码结构。
`--self-test` 钉住两种正例与三种回归形状。
`scripts/test_ci_job_contracts.py` 再断言这两处接线不会被悄悄摘掉。

教训：凡是「契约由源码 + 配套测试共同表达」的地方，必须有一层读源码字节的守卫，
不能只依赖会随代码一起被改短的测试运行器。
