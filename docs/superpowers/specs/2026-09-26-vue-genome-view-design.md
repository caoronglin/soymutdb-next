# 零 React Vue 基因组视图：设计说明（2026-09-26）

**文档用途：** 定义把 `apps/jbrowse` 从 `@jbrowse/react-linear-genome-view` 迁移到自研 Vue 基因组视图的目标架构、包边界、数据契约、错误与测试策略、迁移顺序与验收标准。本文是子项目 A/B/C 的 spec；D–G 只在第 13 节列出边界，各自另行成文。

**目标：** 全仓不再依赖 React；基线功能（参考序列、VCF 变异、结构变异、GFF3 基因模型、BigBed 重复、BigWig 定量、比对轨道、Trix 基因搜索、多 assembly、深链、iframe 嵌入、全屏、分享）以 Vue 原生渲染达到对等，且轨道类型/实验能力可由后端配置增减。

**非目标：** 不重写后端数据发布链路；不改变 `apps/web` 的 iframe 嵌入契约；不引入新的权威存储；不为已退役的 Page Builder/Widget 系统（ADR-0009）恢复功能。

---

## 1. 背景与事实基线

- `apps/web`（42 个 `.vue`）、`apps/admin`（21 个 `.vue`）已是 Vue，无 React。
- 仅剩 React 面：`apps/jbrowse`（`App.tsx` + `main.tsx` + `design-system-provider.tsx`）、`packages/motion`（React-only 且无消费者）、`packages/i18n`（react-i18next 适配器，仅 jbrowse 使用）。
- 数据来自 `/jbrowse-data` 静态文件：`BgzipFastaAdapter`、`ChromSizesAdapter`、`VcfTabixAdapter`（变异与结构变异）、`Gff3TabixAdapter`、`BigBedAdapter`、`BigWigAdapter`、`TrixTextSearchAdapter`。
- `@soymutdb/genome-view-model` 已提供区间/重叠/裁剪/行打包数学。
- 门户 `apps/web` 通过 `<iframe>` + `@soymutdb/shared/jbrowse-bridge` 与本应用通信，消息封装为 `{source, version, type, payload}`。
- 所有非 React 读取器已在 pnpm store：`@gmod/indexedfasta`、`@gmod/tabix`、`@gmod/vcf`、`@gmod/bbi`、`@gmod/bgzf-filehandle`、`@gmod/trix`、`@gmod/bam`。

## 2. 总体架构

```text
apps/jbrowse（Vue 外壳：头部、assembly、位点、分享、全屏、bridge、深链、主题）
    └── @soymutdb/genome-view（Vue 组件 + 轨道注册表 + 视口状态）
            └── @soymutdb/genome-view-model（既有：区间/布局数学）
                    └── @soymutdb/genome-data（新：@gmod 读取器 → 归一化记录）
```

依赖方向严格单向向下；`genome-data` 不依赖 Vue，可独立测试。

## 3. 包边界与职责

| 包 | 职责 | 不做什么 |
| --- | --- | --- |
| `@soymutdb/genome-data`（新增） | 静态/远端文件读取、格式解析、归一化、句柄缓存、中止 | 不渲染、不持有 UI 状态、不依赖框架 |
| `@soymutdb/genome-view-model`（扩展） | 坐标换算、视口裁剪、特征布局、轨道堆叠 | 不读取数据、不渲染 |
| `@soymutdb/genome-view`（新增） | Vue 轨道渲染、视口交互、轨道选择、错误边界 | 不直接解析文件格式 |
| `apps/jbrowse`（改造） | 应用外壳、URL/桥接契约、主题、i18n | 不承载可复用的轨道逻辑 |

## 4. 数据层 `@soymutdb/genome-data`（子项目 A）

### 4.1 坐标与 assembly 契约

- 内部统一 **0-based half-open**；与深链/公开边界换算只在 `genome-view-model` 进行。
- 每条记录携带 `assemblyKey`；读取时校验 assembly，不匹配抛 `assembly-mismatch`，绝不跨 assembly 塌缩。
- v4/v5 是不同坐标命名空间：refName 解析必须在该 assembly 的 `refNameAliases`/`chrom.sizes` 内完成。

### 4.2 记录模型

```ts
export interface Region { assemblyKey: string; refName: string; start: number; end: number }

export interface FeatureRecord extends Region {
  id: string; type: string; name?: string; strand?: "+" | "-" | ".";
  score?: number; phase?: number; parentId?: string;
  attributes?: Record<string, string>;
}
export interface VariantRecord extends Region {
  id: string; ref: string; alt: string[];
  kind: "snv" | "mnv" | "ins" | "del" | "sv" | "other";
  quality?: number; info?: Record<string, unknown>;
}
export interface QuantRecord { assemblyKey: string; refName: string; start: number; end: number; score: number }
export interface SequenceChunk { assemblyKey: string; refName: string; start: number; bases: string }
```

### 4.3 读取器

| 接口 | 实现 | 源格式 |
| --- | --- | --- |
| `SequenceReader` | `@gmod/indexedfasta` + `@gmod/bgzf-filehandle` | bgzip FASTA + `.fai`/`.gzi` |
| `ChromSizesReader` | 纯文本解析 | `chrom.sizes` |
| `VariantReader` | `@gmod/tabix` + `@gmod/vcf` | VCF.GZ + `.tbi` |
| `FeatureReader` | `@gmod/tabix` + GFF3 解析 | GFF3.GZ + `.tbi` |
| `QuantitativeReader` | `@gmod/bbi`（BigWig） | `.bw` |
| `IntervalFeatureReader` | `@gmod/bbi`（BigBed） | `.bb` |
| `TextSearchReader` | `@gmod/trix` | `.ix` + `.ixx` |
| `AlignmentReader`（实验） | `@gmod/bam` | BAM + `.bai` |

工厂：`createTrackDataSource(trackConfig, assemblies)` 按后端返回的 `track.type` 选择实现；未知类型抛 `unsupported-type`，由上层决定隐藏。

### 4.4 位置与句柄

```ts
type GenomeLocation =
  | { kind: "uri"; uri: string }
  | { kind: "local"; path: string };
interface FileProvider { open(location: GenomeLocation): Promise<Filehandle> }
```
- LRU 句柄缓存（默认 32），`AbortSignal` 贯穿每次区域读取。
- 测试注入内存 `FileProvider`，不触网。

### 4.5 错误

```ts
class GenomeDataError extends Error {
  code: "fetch" | "parse" | "unsupported-type" | "assembly-mismatch" | "aborted";
  trackId?: string;
}
```
`aborted` 不进入用户可见错误；其余由轨道错误边界呈现。

### 4.6 测试

- Vitest；提交微型 fixture（`.fa.gz/.fai/.gzi`、`.vcf.gz/.tbi`、`.gff3.gz/.tbi`、`.bw`、`.bb`、`.ix/.ixx`）或程序化构造。
- 覆盖：区域边界、空区域、未知类型、assembly 不匹配、中止、畸形行。

## 5. Vue 视图 `@soymutdb/genome-view`（子项目 B）

### 5.1 视口状态
`useGenomeViewport()`（`reactive`/Pinia）持有 `{ assemblyKey, refName, start, end, bpPerPx }`；动作 `panTo/zoomBy/gotoLocus`；所有变更去抖后触发各轨道区域查询。

### 5.2 轨道注册表
```ts
registerTrackRenderer(type, { component, requiredCapability? })
```
- 后端 `/tracks/jbrowse-config` 返回可用轨道；能力 API 决定实验轨道是否可用。
- 未知/未启用类型在 UI 中隐藏并在控制台记录一次，绝不渲染空白轨道。

### 5.3 渲染
- Canvas：变异、定量、密集特征（优先，按 DPR 与视口裁剪）。
- SVG：基因模型（复用 `GeneModelPreview.vue` 的转录本布局思路）。
- 组件：`GenomeBrowser.vue`、`TrackRuler.vue`、`TrackSelector.vue`、`LocusSearch.vue`、`TrackErrorBoundary.vue`。

### 5.4 交互与可访问性
拖拽平移、滚轮/按钮缩放、键盘可达的缩放与位点跳转、可见焦点环、`prefers-reduced-motion` 与 `prefers-reduced-data` 降级、屏幕阅读器状态文本。

### 5.5 测试
`@vue/test-utils` + 现有 jsdom 环境；覆盖视口数学、轨道注册、错误边界、键盘交互。视觉回归非必需。

## 6. 外壳 `apps/jbrowse`（子项目 C）

- `main.tsx → main.ts`、`App.tsx → App.vue`、`design-system-provider.tsx → @soymutdb/ui-vue` 主题/Provider。
- **外部契约逐字节保留**：`?assembly/locus/tracks/release/portalOrigin`、`loc` 旧别名、1-based↔0-based 换算、bridge 的 `source/version/type` 与 `ready/error/locus-change/selection-change/init`、origin 校验、standalone 模式不向 opener 发消息。
- i18n 改用 `@soymutdb/i18n-core` 的 Vue 绑定；删除 `@soymutdb/i18n` 使用。
- 构建仍由 Vite 产出，供 `scripts/build-pages-artifact.sh` 组装，受 `VITE_JBROWSE_ENABLED` 门控。

## 7. 后端可调

轨道清单、类型与实验能力由 `/tracks/jbrowse-config` 与 capabilities API 决定；服务端可禁用某类型，客户端优雅降级，无需前端重建。

## 8. 错误处理

分层 typed error；每个轨道独立错误边界（单轨道失败只显示内联错误与重试，不拖垮整视图）；初始化失败显示可重试错误态；`aborted` 静默。

## 9. 测试矩阵

| 层 | 工具 | 关键断言 |
| --- | --- | --- |
| genome-data | vitest + fixtures | 格式解析、坐标、assembly 隔离、中止、错误码 |
| genome-view-model | vitest | 视口裁剪、行打包、坐标换算 |
| genome-view | vitest + @vue/test-utils | 注册表、错误边界、键盘、渲染分支 |
| apps/jbrowse 契约 | node --test | 无任何 React/`@jbrowse/react-*` 依赖；bridge/深链契约不变 |
| 门户嵌入 | Playwright | iframe 加载、ready、locus 往返、超时/错误态 |

## 10. 迁移顺序与回滚

1. 先修 pnpm 状态目录（见 §11），使依赖变更可离线重算 lockfile。
2. 建 `genome-data`（可独立合并，不动现有应用）。
3. 建 `genome-view` 组件与测试（可独立合并）。
4. 在 `apps/jbrowse` 内以开关同时挂载新旧实现，跑门户 E2E 对齐行为。
5. 对等后删除 React 外壳与 `@jbrowse/react-linear-genome-view` 等依赖（子项目 D/E），本地/CI 验证 `--frozen-lockfile`。
6. 回滚点：第 4 步提交与第 5 步提交各自可 revert；数据层/组件层可独立 revert。

## 11. 风险与前置

- **pnpm 状态目录在工作区外**导致 `unable to open database file`：实现前需把 `PNPM_HOME/XDG_DATA_HOME/XDG_CACHE_HOME` 指到工作区内，或在一次受限的 `danger-full-access` 批准下执行 `pnpm install --offline` 重算 lockfile。所有 `@gmod/*` 已在 store，可离线。
- **数据文件存在性**：开发/E2E 环境必须能提供 `/jbrowse-data`，或测试用内存 `FileProvider` 注入 fixture。
- **性能**：全量 CJK 字体与轨道数据体积；渲染须视口裁剪，禁止整段加载。
- **契约回归**：门户 iframe 契约与深链一旦改变即为破坏性，必须由第 9 节契约测试守护。
- **工作量**：A/B/C 是多轮工程，不承诺单次交付；每阶段独立验收。

## 12. 验收标准

- 全仓 `package.json` 与源码不再出现 `react`、`react-dom`、`react-i18next`、`@tanstack/react-query`、`lucide-react`、`@jbrowse/react-*`（子项目 D/E 后）。
- `pnpm install --frozen-lockfile` 通过；各包 `lint/typecheck/test` 通过。
- §9 全部门禁通过；门户嵌入 E2E 通过。
- 后端可禁用某一轨道类型且前端不崩。
- `docs/dev/database-core-contract.md` 的 assembly/身份/可见性约束不被破坏。

## 13. 后续子项目（各自另行 spec）

- **D**：退役 `packages/motion`（无消费者）与 `packages/i18n` 的 React 适配器。
- **E**：依赖与 lockfile 清理，移除 React 相关依赖与 `@vitejs/plugin-react`，更新治理/knip 配置。
- **F**：管理端/公共站功能对等（导入 studio 上传/校验/提交、真实 Dashboard 指标、新闻双语编辑/预览/回收站等）。
- **G**：文档、Wiki、CI 与脚本更新（`.cnb.yml`/`scripts` 中 React 产物路径）。
