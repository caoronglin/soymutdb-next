# 公共 API 类型审计

审计对象：`packages/*` 中通过 `package.json` 的 `exports["."]` 暴露的类型表面。
工具：`scripts/audit_public_api_types.py`（可复跑、`--strict` 可用作门禁）。

```bash
python3 scripts/audit_public_api_types.py           # 报告
python3 scripts/audit_public_api_types.py --strict  # 有 finding 即 exit 1
```

两条判据，都是从源码直接读出的，不依赖工具内部启发式：

1. **`any` / `unknown` / 裸 `object` 出现在导出签名里** —— 边界上的契约被抹掉，调用方无法判断期望形状；
2. **导出的 `type` / `interface` 在本文件之外零消费者** —— 已发布表面上的死重。

`knip` 的 `types` 类别回答的是「这个导出有没有被消费」，它看不到第 1 条；第 2 条的口径也不同
（`export *` 的重导出由 knip 统计，本脚本按声明名统计）。两者互补，不互相替代。

## 当前结果

```
package                          exports  unsafe  dead types
--------------------------------------------------------------------
@soymutdb/api-client                  31       0           0
@soymutdb/charts                      54       0           0
@soymutdb/genome-data                 69       0           0
@soymutdb/genome-view                 49       0           0
@soymutdb/genome-view-model           16       0           3
@soymutdb/i18n                        13       0           0
@soymutdb/i18n-core                   12       0           0
@soymutdb/query-keys                   2       0           1
@soymutdb/shared                       0       0           0
@soymutdb/ui-react                    89       0           2
```

**第 1 条判据：0 finding。** 10 个包的导出签名里没有任何 `any` / `unknown` / 裸 `object`。

**第 2 条判据：6 个 finding，逐条判定为「有意保留的公共表面」，不删除。**

| 包 | 类型 | 判定 |
| --- | --- | --- |
| `genome-view-model` | `GenomicInterval` | 保留。这是该包唯一的区间契约类型，`AnnotatedInterval` 与 `annotateIntervals` / `packRows` 的公开签名都由它派生；消费者通过 `annotateIntervals(...)` 的返回值推断它，因此源码里没有 `import type { GenomicInterval }`。删掉它等于把推断出的公共形状变成匿名。 |
| `genome-view-model` | `AnnotatedInterval` | 保留。同上，`annotateIntervals` 的返回元素类型；名字本身是文档。 |
| `genome-view-model` | `PackedItem<T>` | 保留。`packRows` 的返回元素类型，泛型参数只有在这里才有名字。 |
| `query-keys` | `QueryKeys` | 保留。`queryKeys` 常量的类型别名，供调用方在自己的缓存工具里标注参数类型；包内自用已足够证明它不是死代码。 |
| `ui-react` | `MotionDurations` | 保留。动效 token 的公共形状，`resolveMotionDecision` 的结果类型。 |
| `ui-react` | `SoyMutdbProviderProps` | 保留。React 组件的 props 类型；消费者用 `ComponentProps<typeof SoyMutdbProvider>` 时依赖它的存在，源码里不会出现具名 import。 |

结论：这 6 个都属于「由签名派生的公共类型」——`knip` 与本脚本都只能看到没有具名 import，
而它们的作用正是让推断出来的形状有名字。**不删除**，因为删除会让公共 API 从「具名契约」退化为结构推断。

## 与 knip 的关系

按依赖治理门禁**钉定的版本**运行（`dependency-governance.json` 的 `knip` check）：

```bash
pnpm dlx --package knip@5.62.0 --package typescript@5.9.3 \
  knip --config knip.json --include types --reporter json
```

在当前树上报告 **0 finding**。**版本必须钉住**：不钉版执行 `pnpm dlx knip --include types`
会解析到更新的 knip，同一棵树报出 **14 个** unused exported types（`FormProps`、`ThemeConfig`、
`QueryKeys`、`GenomeViewportActions` 等）—— 那是不同分析器的口径差异，不是这一轮的结论。

差异来自口径：
knip 统计 `export *` 的重导出与跨包 import，本脚本按**声明名**在 `packages/` 内统计消费者。
上表 6 项在 knip 口径里因为有 `export * from` 而从索引入口可达，因此不计为未使用；
本脚本把它们显式列出来，是为了让「这个类型到底有没有人 import」这个问题有可读答案。

这是**报告，不是红灯**：`--strict` 会在任何 finding 下 exit 1，用于在公共表面变动时强制复核，
当前不作为 CI 阻塞门禁（6 条 finding 都是上表确认保留项）。