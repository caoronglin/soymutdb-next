# web-ui → Ant Design removal spec (apps/web)

> **已归档（2026-10-01）**：Vue / React 迁移期文档（Vue 已退役，React 为唯一生产路径）。继任：docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

Goal: delete `src/lib/web-ui.tsx`. Replace its exports with Ant Design directly.
Components come from `@/lib/antd`, icons from `@ant-design/icons`, the toast
hook from `@/lib/toast`, class-joiner from `@/lib/cn`, format helpers from
`@/lib/format`.

Below is the exact mapping. **Preserve behavior, data, i18n keys, `data-testid`,
and accessibility attributes.** Layout/spacing CSS classes on plain elements may
change to AntD equivalents, but do not change business logic.

## Simple 1:1 swaps (import path only)

| web-ui symbol | new import |
|---|---|
| `Button` | `@/lib/antd` Button |
| `Input` | `@/lib/antd` Input (use `prefix`/`placeholder` props) |
| `Textarea` | `@/lib/antd` Input.TextArea |
| `Badge` | `@/lib/antd` Tag (`color=...`) |
| `Select` (compound) | `@/lib/antd` Select with `options` |
| `Tabs` (compound) | `@/lib/antd` Tabs with `items` |
| `Pagination` | `@/lib/antd` Pagination |
| `Skeleton` | `@/lib/antd` Skeleton |
| `EmptyState` | `@/lib/antd` Empty |
| `ChartEmptyState` | `@/lib/antd` Empty (inline overlay) |
| `LoadingState` | `@/lib/antd` Spin / Skeleton |
| `ErrorState` | `@/lib/antd` Result |
| `useToast` | `@/lib/toast` useToast |
| `cn` | `@/lib/cn` cn |
| `formatNumber/formatPercent/formatFileSize/truncate` | `@/lib/format` |

## Button
web-ui: `<Button variant="ghost" size="icon" icon={<X/>} />`
antd:   `<Button type="text" icon={<X/>} />`
- `variant="ghost"`→`type="text"`; `variant="link"`→`type="link"`;
  `variant="destructive"`→`type="primary" danger`; `default`/`hero`→`type="primary"`;
  `outline`/`secondary`→`type="default"`.
- `size="sm"`→`size="small"`; `size="lg"|"xl"`→`size="large"`; `size="icon"`→ omit (default middle, icon-only).
- Remove `asChild`. If the button wraps a router `<Link>`, use antd Button
  `onClick={() => navigate({to})}` or, when it is a plain external anchor,
  `href={...}`. If nested inside a button is unavoidable, replace with a styled
  `<Link>` carrying the same classes and `data-testid`.

## Card family → native antd Card
web-ui:
```
<Card><CardHeader><CardTitle>Title</CardTitle><CardDescription>Desc</CardDescription></CardHeader><CardContent>Body</CardContent></Card>
```
antd:
```
<Card title={<> <Typography.Title level={5}>Title</Typography.Title> <Typography.Text type="secondary">Desc</Typography.Text> </>} ...>Body</Card>
```
- If a card has no header, use `<Card>{body}</Card>`.
- If only content, `CardContent` body is the Card children; `<Card styles={{ body: { padding: 0 } }}>` matches the old flush body when the card was used as an image/wrapper card.
- Body padding: antd default is fine; do not force 0 unless the card wraps full-bleed content.

## PageHeader → Typography + Breadcrumb
web-ui `<PageHeader title=... description=... icon=... breadcrumb=... actions=.../>`
→
```
<header className="flex flex-col gap-4">
  {breadcrumb && <Breadcrumb items={...}/>}
  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
    <div className="flex items-start gap-3.5">
      {icon && <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">{icon}</span>}
      <div>
        <Typography.Title level={2} style={{margin:0}}>{title}</Typography.Title>
        {description && <Typography.Paragraph type="secondary" style={{margin:0}}>{description}</Typography.Paragraph>}
      </div>
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </div>
</header>
```
Use `@/lib/antd` `Breadcrumb`, `Typography`.

## StatCard
web-ui `<StatCard label value icon trend>` → antd `Card` + `Statistic`:
```
<Card><Statistic title={label} value={value} prefix={icon} /></Card>
```
If `trend` present, render it as a `Tag` or small `Typography.Text` under the value.

## ToastProvider / nested provider
Remove any `<ToastProvider>` wrapper entirely (AntD `<App>` is at the root via
DesignSystemProvider). Import `useToast` from `@/lib/toast` and keep the
existing destructure call sites.

## Do NOT
- Leave any `web-ui` import.
- Import from the `antd` root — only via `@/lib/antd`.
- Change route paths, query keys, API calls, or test ids.

After editing, run `npx eslint <files>` and fix introduced errors, then report:
per file, the symbol replacements done and anything you could NOT fully
convert (must be none). If a file is too large and you cannot finish a symbol,
still remove ALL `web-ui` imports and note which symbols you left unresolved in
the report. Do not edit files outside your assigned list.
