# Ant Design migration guide (apps/web)

> **已归档（2026-10-01）**：Vue / React 迁移期文档（Vue 已退役，React 为唯一生产路径）。继任：docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

Goal: make Ant Design the **sole** component + icon library in `apps/web`. Remove
`lucide-react` entirely and remove usages of the custom `lib/web-ui` component
layer in favor of the Ant Design facade `@/lib/antd` + `@ant-design/icons`.

## Rules

1. **Import source.** UI components come from `@/lib/antd` (the facade). Icons
   come from `@ant-design/icons`. Never import from `lucide-react`.
2. **Do not** import from `antd` root — always via `@/lib/antd`.
3. **Do not** render `<button>`/`<a>`/raw table markup if an AntD primitive
   exists (use `Button`, `Table`, `Input`, `Select`, `Dropdown`, etc.).
4. Preserve all behavior, data, i18n keys, test ids (e.g. `data-testid`), and
   accessibility attributes. Do not change route paths or business logic.
5. Keep existing CSS utility classes on non-component elements (layout/spacing
   is fine); the requirement is that interactive UI comes from AntD.
6. After editing, ensure the file still type-checks (no leftover references to
   `lucide-react` or removed `web-ui` symbols).

## Icon mapping (lucide-react → @ant-design/icons)

| lucide-react | @ant-design/icons |
|---|---|
| Activity | RiseOutlined |
| AlertCircle | ExclamationCircleOutlined |
| AlertTriangle | WarningOutlined |
| ArrowDown | ArrowDownOutlined |
| ArrowLeft | ArrowLeftOutlined |
| ArrowRight | ArrowRightOutlined |
| ArrowUp | ArrowUpOutlined |
| ArrowUpDown | SwapOutlined |
| ArrowUpRight | ExportOutlined |
| Ban | StopOutlined |
| BarChart3 | BarChartOutlined |
| Beaker | ExperimentOutlined |
| Bell | BellOutlined |
| BookOpen | ReadOutlined |
| Check | CheckOutlined |
| CheckCheck | CheckOutlined |
| CheckCircle2 | CheckCircleOutlined |
| ChevronDown | DownOutlined |
| CircleCheck | CheckCircleOutlined |
| CircleX | CloseCircleOutlined |
| Command (CmdIcon) | ControlOutlined |
| Database | DatabaseOutlined |
| Dna | DeploymentUnitOutlined |
| Download | DownloadOutlined |
| ExternalLink | ExportOutlined |
| Eye | EyeOutlined |
| File | FileOutlined |
| FileCheck2 | FileProtectOutlined |
| FileText | FileTextOutlined |
| FileWarning | WarningOutlined |
| FlaskConical | ExperimentOutlined |
| FlaskRound | ExperimentOutlined |
| FolderKanban | FolderOpenOutlined |
| Gauge | DashboardOutlined |
| Globe2 | GlobalOutlined |
| HelpCircle | QuestionCircleOutlined |
| Inbox | InboxOutlined |
| Info | InfoCircleOutlined |
| Layers | PartitionOutlined |
| Loader2 | LoadingOutlined |
| LogIn | LoginOutlined |
| Mail | MailOutlined |
| MapPin | EnvironmentOutlined |
| Maximize2 | ExpandOutlined |
| Microscope | AimOutlined |
| Minus | MinusOutlined |
| Network | NodeIndexOutlined |
| Play | CaretRightOutlined |
| Plus | PlusOutlined |
| Rocket | RocketOutlined |
| RotateCcw | RedoOutlined |
| RotateCw | ReloadOutlined |
| ScanSearch | ScanOutlined |
| Search | SearchOutlined |
| ShieldAlert | SafetyOutlined |
| Sparkles | CrownOutlined |
| SunMedium | SunOutlined |
| UploadCloud | CloudUploadOutlined |
| X | CloseOutlined |
| XCircle | CloseCircleOutlined |
| ZoomIn | ZoomInOutlined |
| ZoomOut | ZoomOutOutlined |

Lucide icons and AntD icons accept the same `className`/`style` props and are
used both inline (`<Search className="size-4" />`) and as component values
(`icon={<Search />}`, or `icon={Search}`). Convert both forms.

When a lucide icon was imported under an alias (`Command as CmdIcon`), keep the
alias (`ControlOutlined as CmdIcon`) so JSX usage is unchanged.

## web-ui → @/lib/antd component mapping

| web-ui symbol | AntD replacement |
|---|---|
| Button | Button (map `variant`→`type`, `size`, `icon`; see below) |
| Badge | Tag |
| Card + CardHeader/CardTitle/CardDescription/CardContent | Card + Typography |
| Input | Input (antd) |
| Textarea | Input.TextArea |
| Label | Form.Item label / <label> |
| Select (compound) | Select (antd options) |
| Tabs (compound) | Tabs (antd items) |
| Table family | Table (antd) or keep `<table>` only when used as a layout table |
| Pagination | Pagination (antd) |
| Skeleton | Skeleton (antd) |
| EmptyState | Empty |
| LoadingState | Spin / Skeleton |
| ErrorState | Result |
| PageHeader | Typography.Title + Breadcrumb |
| StatCard | Card + Descriptions/Statistic |
| ChartEmptyState | Empty |
| ToastProvider / useToast | antd `App.useApp()` `message` |
| cn | keep (import from `lib/format` or a `lib/cn`) |
| formatNumber/formatPercent/formatFileSize/truncate | keep (import from `lib/format`) |

### web-ui Button → antd Button

- delete the `asChild` prop; if the button wraps a router `<Link>`, prefer
  `onClick={() => navigate({to})}` or antd `Button` `href` when it is a plain
  anchor. If `asChild` is required, wrap the content in an inline anchor styled
  by the consumer or keep antd `Link` inside the button text.
- `variant="ghost"` → `type="text"`; `variant="link"` → `type="link"`;
  `variant="destructive"` → `type="primary" danger`; the rest → `type="primary"`
  for `default`/`hero`, `type="default"` for `outline`/`secondary`.
- `size="sm"` → `size="small"`; `size="lg"|"xl"` → `size="large"`;
  `size="icon"` → keep `size="middle"` and pass only an `icon` with no text.
- Convert `icon={<X/>}` form stays valid on antd Button.

> If you cannot fully remove a `web-ui` symbol without restructuring a card
> layout, keep the import from `web-ui` for that symbol **only** and still
> remove all lucide usage — note it in your summary so the integrator can
> finish it.
