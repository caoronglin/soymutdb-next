# 基线核验记录（基线负责人任务，2026-10-23）

本文件是既有工作记录 `docs/aegis/work/2026-10-20-fullstack-stabilization/` 的一个 sidecar，
记录「基线负责人」阶段对既有基线分支与 Draft PR 的独立核验结论。
未新增工作流、未新建计划文件、未改动任何业务代码。

## 1. 原始目标（本阶段授权范围）

用户授权：

- 先将当前已有项目改动安全保存至 `baseline/workspace-20261020` 独立分支；
- 创建指向 `caoronglin/soymutdb-next` `main` 的 Draft 基线 PR；
- 不合并、不改写历史，排除凭据/缓存/构建产物；
- 历史提示已有 PR #26、commit `57e2bcd`、612 个文件 —— **必须实际核验 git/远端 PR 状态，不得重复创建**；
- 基线已存在且正确则不重做，只报告工作区与基线差异及能否推进；
- 本阶段不审计/修复业务代码、不升级依赖。

禁止项（均已遵守）：强推、`reset`/`clean`、删除未知文件、自动合并、打印秘密。

## 2. 实际基线与分支 HEAD（核验后，非沿用历史声明）

| 对象 | 值 | 来源 |
| --- | --- | --- |
| 基线分支 | `baseline/workspace-20261020` | 本地 `git branch -vv` |
| 基线 commit | `57e2bcdee3bab3435578997dba85cf26c3b985bc` | `git rev-parse` |
| 基线 parent | `166f76bda6ed347af86c658d374c3525995c6a11`（`chore/node-26-pin-20261010`） | `git rev-parse ...^` |
| 远端同名分支 | `57e2bcdee…`（与本地同一 SHA） | `git ls-remote --heads origin` |
| Draft PR | [#26](https://github.com/caoronglin/soymutdb-next/pull/26) | `gh pr view 26` |
| PR 状态 | `state=OPEN`、`isDraft=true`、`mergedAt=null` | `gh pr view --json` |
| PR base | `main` → `1e9c1af6c5b10e0500f2826e451017962ec64d00`（= `origin/main`） | `gh pr view --json` |
| PR head | `baseline/workspace-20261020` → `57e2bcdee…`（= 本地基线 SHA） | `gh pr view --json` |
| PR 规模 | 相对 base 672 files / +78463 / −19971；26 commits | `gh pr view --json` |
| 当前工作分支 | `fix/fullstack-stabilization-20261020` | `git status -b` |
| 当前 HEAD | `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（`docs(plan): define incremental full-stack stabilization scope`） | `git rev-parse HEAD` |
| 当前工作树 | dirty：65 个已跟踪修改 + 28 个未跟踪文件 | `git status --porcelain=v1` |

分支关系：`baseline/workspace-20261020` 是当前 HEAD 的祖先（`git merge-base --is-ancestor` → YES）；
基线相对 `origin/main` 领先 26 个提交，反向 0 个提交，`origin/main` 是基线的祖先
（`git merge-base baseline origin/main` = `1e9c1af6`）。因此 PR #26 的 base/head 关系是干净的快进方向，无冲突历史。

**结论：基线已存在且正确，本阶段不重做、不新建 PR、不新推分支、不产生新提交。**

### 2.1 对既有声明的继承性核验

本记录 `20-checkpoint.md:5` 此前写的是「基线 Draft PR #26 已保存、未合并（历史结果，本轮未查询远端）」。
本次**实际查询了远端**，结论与该声明一致：PR #26 仍为 OPEN + Draft + 未合并，且 head SHA 与本地基线分支一致。
声明成立，无需纠正。

## 3. 基线是否真正冻结了「既有改动」——缺口检验

历史提交只说明「612 个文件的快照」，未证明「快照 == 冻结时刻的工作区全貌」。
用 mtime 相对基线提交时刻（2026-10-20 14:57:08 +0800）做差分检验：

- 65 个已跟踪差异文件与 28 个未跟踪文件的**最早 mtime 为 2026-10-20 15:05:14**；
- 没有任何一个差异文件（已跟踪或未跟踪）的 mtime 早于基线提交时刻；
- `git stash list` 为空，无被搁置的工作区内容。

即：**当前工作区相对基线的全部差异都发生在基线提交之后**，它们是 Task 1–5 的在飞稳定性修复
（属于 `fix/fullstack-stabilization-20261020`，不应进入基线快照）；
基线提交之前就存在的未提交改动已全部被 `57e2bcdee` 收纳，不存在基线缺口。

## 4. 敏感文件筛查（方法与限制）

筛查对象为基线提交 `57e2bcdee` 的 612 个路径及其树内容。

### 4.1 方法

1. **路径名筛查**（`git show --name-only` + 正则）：凭据类
   `\.env(\.|$)`、`credentials?`、`\.netrc`、`\.npmrc`、`\.pypirc`、`id_rsa|id_ed25519`、
   `\.pem$|\.key$|\.p12$|\.pfx$`、`secrets?\.`、`\.aws/`、`known_hosts`；
   缓存/产物类
   `node_modules`、`__pycache__`、`\.venv|venv`、`\.mypy_cache|\.pytest_cache|\.ruff_cache|\.turbo`、
   `dist|build|coverage`、`\.cache|\.nyc_output|target|\.tox|\.gradle`；
   工具链/本地态 `\.next|\.output|\.vite|site-packages|\.pnpm-store|\.deploy/bin`。
2. **强制加入检测**：`git show --name-only | git check-ignore --stdin`
   —— 命中即为「被 ignore 但仍被跟踪」的强制 `-f` 加入。
3. **值模式筛查**（`git grep -l -I -E <pattern> 57e2bcdee`，**只输出文件名，不输出命中行**）：
   私钥头 `-----BEGIN [A-Z ]*PRIVATE KEY-----`、`AKIA[0-9A-Z]{16}`、`ghp_[A-Za-z0-9]{20,}`、
   `github_pat_`、`sk-[A-Za-z0-9]{20,}`、`xox[baprs]-`、`AIza[0-9A-Za-z_-]{30,}`、
   JWT 形态 `eyJ…\.…\.`；以及赋值型
   `(password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[=:]\s*["'][^"']{8,}`。
4. **体量筛查**：`git ls-tree -r -l` 取最大 blob 与 >2MiB 文件计数。
5. **本地态目录核对**：`git ls-tree -r --name-only 57e2bcdee -- <dir>` 逐个确认
   `.validation`、`.local-pg`、`.ph`、`.cache`、`.mamba-root`、`.deploy/bin` 均未被纳入。
6. **模板件复核**：对 `apps/api/.env.example`、`deploy/.env.example` 只提取键名，值一律不打印。

### 4.2 结果

- 凭据类路径命中 **2 个**，均为模板：`apps/api/.env.example`、`deploy/.env.example`。
  逐键复核后确认全部为占位/空值或注释掉的示例（如 `# SOYMUTDB_GITHUB_PAGES_TOKEN=ghp_xxxx` 是字面占位串）。
  全仓库无被跟踪的真实 `.env`（`git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.example$'` → 空）；
  工作区根、`apps/api/`、`deploy/` 下均无真实 `.env` 文件。
- 缓存/构建产物路径命中 **0**。
- 强制加入（tracked-but-ignored）命中 **0**。
- 值模式 8 类命中文件数全部为 **0**；赋值型秘密字面量命中 **0**。
- 最大 blob 2.43 MiB（`docs/design/references/ui-r/网页-核查V2.pdf`），>2MiB 文件仅 **1** 个。
- `.validation` / `.local-pg` / `.ph` / `.cache` / `.mamba-root` / `.deploy/bin` 纳入数量均为 **0**。

### 4.3 限制（不得当作完整安全审计）

- 筛查只覆盖**基线提交这一个提交**新增/修改的内容与路径名，不覆盖基线之前 25 个既有提交的历史内容。
- 正则是**已知模式族**，不检测未知格式的凭据、编码后的秘密、二进制内嵌秘密、私钥加密包、
  历史提交中被删除但仍可从对象库取回的内容（`git log -p` 全历史扫描本次未做）。
- `.env.example` 的「是模板」结论基于逐键人工复核（值未打印），不是自动化模板比对。
- 未做凭据有效性验证（不访问任何凭据服务），因此「占位/有效」只到形态层面。
- 该结论与 PR #26 正文中的既有声明一致：**不等于完整安全审计**。

## 5. 远端 PR 的 CI 状态（须如实记录）

`gh pr checks 26`：17 个 job 全部 `fail`，用时 2–3 秒，`steps: []`（从未真正执行）。
`check-runs/.../annotations` 给出的原因一致：

> The job was not started because recent account payments have failed or your spending limit needs to be increased.

这是**账户级 Actions 计费/额度问题，不是代码失败**。因此当前 GitHub 侧无法作为门禁使用；
本阶段不得以「CI 红」解读为基线内容有问题，也不得以「PR 开了」解读为已验证。

## 6. 工作区与基线的差异（供阶段 2 判断）

相对 `baseline/workspace-20261020`：

- **已提交差异 1 个 commit**：`01fc163a4`（仅新增设计文档
  `docs/superpowers/specs/2026-10-20-fullstack-stabilization-design.md`，+32 行）。
- **已跟踪修改 65 个文件**（`git diff --stat baseline..worktree`：+2813 / −585），覆盖
  `apps/api`（变异公开可见性、导出服务、仓储、路由、schema）、`apps/worker`（导出生命周期、仓储、task）、
  `packages/jobs-py`（共享 artifact/error 契约）、`apps/web` + `apps/admin` + `apps/jbrowse`（前端接线与测试）、
  `packages/api-client` + `packages/query-keys` + `packages/i18n-core`、
  `scripts/`（native export chain、worker task registry）、`e2e/`、`docs/aegis/INDEX.md`。
- **未跟踪 28 个文件**：新模型/服务/迁移（`0049_variant_exports.py` 等）、新测试、
  `packages/jobs-py/src/soymutdb_jobs/export_artifact.py` 与 `export_errors.py`、
  `docs/aegis/plans/2026-10-20-fullstack-stabilization.md` 与本工作记录目录。

归属判定：这些差异全部落在已批准的 Task 1–5 范围内（浏览器上下文链路、变异公开筛选与导出边界、
全局搜索分页、株系检索/预览链接、作业/下载/MCP 扩展），**不是**「基线应收纳而漏收」的既有改动。
归属清晰，无不明来源变动，不需要停写。

## 7. 阶段计划与范围（基线已确认后在此记录）

阶段 1（基线负责人）——**已完成**：

- 核验基线分支与 Draft PR #26 的本地/远端一致性 → 一致，无需重做；
- 敏感文件筛查 → 通过（含方法与限制记录）；
- 确认无历史改写、无强推、无自动合并、无 stash 遗留；
- 在既有工作记录中建立本基线核验 sidecar（未污染已冻结的基线快照：本记录目录为未跟踪状态，
  不在 `57e2bcdee` 内，也未加入任何提交）。

阶段 2（Lead 调度）——**可进入**，前置条件已满足：

- 基线锚点明确且未被改写：`57e2bcdee`（PR #26，Draft，base=main，未合并）；
- 阶段 2 起点应基于 `fix/fullstack-stabilization-20261020`（`01fc163a4`）之上继续，
  **不要**把在飞的 Task 1–5 改动倒灌进基线分支；
- 已知约束：GitHub Actions 因账户计费不可用，本阶段门禁只能靠本机验证；
  本机 PG 为 16.15（≠ CI 的 PG 18），本机绿只能证明「在 PG 16 上绿」；
  依 `.ai-memory/LOCAL-RUN-ENV.md`，Node 26 走 `/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin`，
  `PNPM_HOME="$PWD/.ph"`，turbo 需 `--concurrency=1`。
- 本阶段遗留提醒：PR #26 的 17 个 CI job 需在计费恢复后重跑（代码侧无需改动）。

## 8. 本阶段未做的事（明确边界）

未审计/修复任何业务代码；未升级任何依赖；未修改任何源文件；
未创建分支、提交、推送或 PR；未合并、未关闭 PR；未 force-push、未 `reset`/`clean`、
未删除任何文件（含 3 个既有 detached validation checkout 与本机 PG/测试数据，均保留）。
