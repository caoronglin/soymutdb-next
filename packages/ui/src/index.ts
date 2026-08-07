/**
 * @soymutdb/ui — Shared shadcn/ui component library.
 *
 * new-york style, green baseColor, OKLCH design tokens.
 * Import the stylesheet once in the app root: `import "@soymutdb/ui/styles.css"`.
 */

// Utilities
export {
  cn,
  formatNumber,
  formatPercent,
  formatFileSize,
  truncate,
  validatePasswordStrength,
  getPasswordStrengthLabel,
  type PasswordValidationResult,
} from "./lib/utils";

// Primitives
export { Button, buttonVariants } from "./components/button";
export { Badge, badgeVariants } from "./components/badge";
export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
} from "./components/card";
export { Input } from "./components/input";
export { Label } from "./components/label";
export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
} from "./components/select";
export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
} from "./components/table";
export { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/tabs";
export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "./components/dialog";
export { Skeleton } from "./components/skeleton";
export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "./components/tooltip";
export { Textarea } from "./components/textarea";
export {
  Pagination,
  type PaginationProps,
} from "./components/pagination";
export { StatCard, type StatCardProps } from "./components/stat-card";
export {
  EmptyState,
  type EmptyStateProps,
  type EmptyStateMode,
} from "./components/empty-state";
export {
  ChartEmptyState,
  type ChartEmptyStateProps,
} from "./components/chart-empty-state";

// Data display & states
export {
  DataTable,
  type DataTableProps,
  type DataTableColumn,
  type DataTableSort,
  type DataTableSelection,
  type DataTableColumnVisibility,
} from "./components/data-table";
export { PageHeader, type PageHeaderProps, type PageHeaderBreadcrumbItem } from "./components/page-header";
export { FilterBar, type FilterBarProps, type FilterItem } from "./components/filter-bar";
export {
  ResponsiveDataView,
  type ResponsiveDataViewProps,
  type ResponsiveDataViewStatus,
} from "./components/responsive-data-view";
export { LoadingState, type LoadingStateProps } from "./components/loading-state";
export { ErrorState, type ErrorStateProps } from "./components/error-state";
export { DemoState, type DemoStateProps } from "./components/demo-state";
export {
  ToastProvider,
  useToast,
  type ToastProviderProps,
  type ToastContextValue,
  type ToastItem,
  type ToastOptions,
  type ToastPosition,
  type ToastVariant,
} from "./components/toast";
