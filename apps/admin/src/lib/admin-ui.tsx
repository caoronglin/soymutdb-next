import * as React from "react";
import {
  Button as AntButton,
  Card as AntCard,
  Modal,
  Pagination as AntPagination,
  Select as AntSelect,
  Tag,
  type ButtonProps as AntButtonProps,
} from "antd";
import { BarChart3, ChevronRight, type LucideIcon } from "lucide-react";

type ClassValue = string | false | null | undefined;

/** Small dependency-free class-name joiner for conditional Tailwind classes. */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unit).toFixed(1)} ${units[unit]}`;
}

type ButtonVariant =
  | "default"
  | "destructive"
  | "outline"
  | "secondary"
  | "ghost"
  | "link"
  | "hero";
type ButtonSize = "default" | "sm" | "lg" | "xl" | "icon";

export interface ButtonProps
  extends Omit<AntButtonProps, "danger" | "htmlType" | "size" | "type" | "variant"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  type?: "button" | "submit" | "reset";
}

/** Compatibility surface backed by AntD Button while Admin screens migrate. */
export function Button({
  variant = "default",
  size = "default",
  type = "button",
  className,
  ...props
}: ButtonProps) {
  const antType =
    variant === "ghost"
      ? "text"
      : variant === "link"
        ? "link"
        : variant === "default" || variant === "destructive" || variant === "hero"
          ? "primary"
          : "default";
  const antSize = size === "sm" ? "small" : size === "lg" || size === "xl" ? "large" : "middle";
  return (
    <AntButton
      {...props}
      type={antType}
      htmlType={type}
      danger={variant === "destructive"}
      size={antSize}
      shape={size === "icon" ? "circle" : undefined}
      className={className}
    />
  );
}

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
}

export function Badge({ variant = "default", className, children, ...props }: BadgeProps) {
  const color =
    variant === "success"
      ? "green"
      : variant === "warning"
        ? "gold"
        : variant === "destructive"
          ? "red"
          : variant === "default"
            ? "green"
            : undefined;
  return (
    <Tag
      {...props}
      color={color}
      variant={variant === "outline" ? "outlined" : "filled"}
      className={className}
      style={{ marginInlineEnd: 0, ...props.style }}
    >
      {children}
    </Tag>
  );
}

export function Card({ children, ...props }: React.ComponentProps<typeof AntCard>) {
  return (
    <AntCard {...props} styles={{ body: { padding: 0 }, ...props.styles }}>
      {children}
    </AntCard>
  );
}

export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("border-b border-border/60 px-5 py-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return <h3 className={cn("text-base font-semibold", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("p-5", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex items-center px-5 py-4", className)} {...props} />;
}

export const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-primary disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          "min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);

export function Label({ className, ...props }: React.ComponentProps<"label">) {
  return <label className={cn("text-sm font-medium", className)} {...props} />;
}

interface SelectMarkerProps {
  children?: React.ReactNode;
  className?: string;
  id?: string;
  placeholder?: React.ReactNode;
  value?: string;
  disabled?: boolean;
}

export function SelectTrigger(_props: SelectMarkerProps) {
  return null;
}

export function SelectValue(_props: SelectMarkerProps) {
  return null;
}

export function SelectContent(_props: SelectMarkerProps) {
  return null;
}

export function SelectItem(_props: SelectMarkerProps) {
  return null;
}

function markerProps(node: React.ReactNode): SelectMarkerProps | null {
  return React.isValidElement(node) ? (node.props as SelectMarkerProps) : null;
}

function selectOptions(children: React.ReactNode): Array<{ label: React.ReactNode; value: string; disabled?: boolean }> {
  const options: Array<{ label: React.ReactNode; value: string; disabled?: boolean }> = [];
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;
    const props = child.props as SelectMarkerProps;
    if (child.type === SelectItem && props.value !== undefined) {
      options.push({ label: props.children, value: props.value, disabled: props.disabled });
      return;
    }
    selectOptions(props.children).forEach((option) => options.push(option));
  });
  return options;
}

export interface SelectProps {
  children: React.ReactNode;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  onValueChange?: (value: string) => void;
}

/** Compound Select API rendered as one AntD Select. */
export function Select({ children, value, defaultValue, disabled, onValueChange }: SelectProps) {
  const childArray = React.Children.toArray(children);
  const trigger = childArray.find(
    (child) => React.isValidElement(child) && child.type === SelectTrigger,
  );
  const triggerConfig = markerProps(trigger);
  const valueMarker = React.Children.toArray(triggerConfig?.children).find(
    (child) => React.isValidElement(child) && child.type === SelectValue,
  );
  const placeholder = markerProps(valueMarker)?.placeholder;
  return (
    <AntSelect
      id={triggerConfig?.id}
      className={triggerConfig?.className}
      style={{ width: "100%" }}
      value={value}
      defaultValue={defaultValue}
      disabled={disabled}
      placeholder={placeholder}
      options={selectOptions(children)}
      onChange={(next) => onValueChange?.(String(next))}
    />
  );
}

interface DialogContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DialogContext = React.createContext<DialogContextValue | null>(null);

export function Dialog({
  open,
  onOpenChange,
  children,
}: DialogContextValue & { children: React.ReactNode }) {
  return (
    <DialogContext.Provider value={{ open, onOpenChange }}>
      {children}
    </DialogContext.Provider>
  );
}

export function DialogContent({
  children,
  className,
  onKeyDown,
}: React.ComponentProps<"div">) {
  const dialog = React.useContext(DialogContext);
  if (!dialog) return null;
  return (
    <Modal
      open={dialog.open}
      onCancel={() => dialog.onOpenChange(false)}
      footer={null}
      destroyOnHidden
    >
      <div className={className} onKeyDown={onKeyDown}>
        {children}
      </div>
    </Modal>
  );
}

export function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("mb-4", className)} {...props} />;
}

export function DialogTitle({ className, ...props }: React.ComponentProps<"h2">) {
  return <h2 className={cn("text-lg font-semibold", className)} {...props} />;
}

export function DialogDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("mt-5 flex justify-end gap-2", className)} {...props} />;
}

export function Table({ className, ...props }: React.ComponentProps<"table">) {
  return <table className={cn("w-full text-sm", className)} {...props} />;
}

export function TableHeader(props: React.ComponentProps<"thead">) {
  return <thead {...props} />;
}

export function TableBody(props: React.ComponentProps<"tbody">) {
  return <tbody {...props} />;
}

export function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return <th className={cn("border-b px-3 py-2 text-left font-medium", className)} {...props} />;
}

export function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return <tr className={cn("border-b", className)} {...props} />;
}

export function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("px-3 py-2", className)} {...props} />;
}

export interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
  label?: string;
  className?: string;
}

export function Pagination({
  page,
  total,
  pageSize,
  onPageChange,
  disabled,
  label = "Pagination",
  className,
}: PaginationProps) {
  return (
    <nav aria-label={label} className={className}>
      <AntPagination
        current={page}
        total={total}
        pageSize={pageSize}
        showSizeChanger={false}
        disabled={disabled}
        onChange={onPageChange}
      />
    </nav>
  );
}

export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("shimmer rounded-md", className)} {...props} />;
}

export interface EmptyStateProps {
  icon?: LucideIcon;
  title?: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, title = "No data", description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-8 py-12 text-center", className)} role="status">
      {Icon ? <Icon className="mb-3 size-8 text-muted-foreground" aria-hidden /> : null}
      <h3 className="font-semibold">{title}</h3>
      {description ? <p className="mt-2 text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export interface PageHeaderBreadcrumbItem {
  label: React.ReactNode;
  href?: string;
}

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: LucideIcon;
  breadcrumb?: PageHeaderBreadcrumbItem[] | React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({ title, description, icon: Icon, breadcrumb, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-4", className)}>
      {Array.isArray(breadcrumb) ? (
        <nav aria-label="Breadcrumb">
          <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
            {breadcrumb.map((item, index) => (
              <li key={index} className="flex items-center gap-1.5">
                {item.href ? <a href={item.href}>{item.label}</a> : <span>{item.label}</span>}
                {index < breadcrumb.length - 1 ? <ChevronRight className="size-3.5" /> : null}
              </li>
            ))}
          </ol>
        </nav>
      ) : breadcrumb ?? null}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3.5">
          {Icon ? <Icon className="mt-1 size-5 text-primary" aria-hidden /> : null}
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            {description ? <p className="mt-1.5 text-sm text-muted-foreground">{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

export interface StatCardProps {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  trend?: { value: string; positive: boolean };
  className?: string;
}

export function StatCard({ label, value, icon, trend, className }: StatCardProps) {
  return (
    <Card className={cn("card-lift", className)}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
          {icon}
        </div>
        <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
        {trend ? (
          <p className={cn("mt-1.5 text-xs font-medium", trend.positive ? "text-emerald-600" : "text-red-500")}>
            {trend.positive ? "↑" : "↓"} {trend.value}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export interface ChartEmptyStateProps {
  visible: boolean;
  message?: string;
  description?: string;
  className?: string;
}

export const ChartEmptyState = React.memo(function ChartEmptyState({
  visible,
  message = "暂无数据",
  description,
  className,
}: ChartEmptyStateProps) {
  return (
    <div
      className={cn(
        "absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-card/80",
        visible ? "opacity-100" : "pointer-events-none opacity-0",
        className,
      )}
      role="status"
      aria-live="polite"
      aria-hidden={!visible}
    >
      <BarChart3 className="size-6 text-muted-foreground" aria-hidden />
      <p className="text-sm font-semibold text-muted-foreground">{message}</p>
      {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
    </div>
  );
});
