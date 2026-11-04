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
