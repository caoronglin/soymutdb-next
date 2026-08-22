import * as React from "react";
import {
  BarChart3,
  ChevronRight,
  LoaderCircle,
  RotateCcw,
  SearchX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import {
  App as AntApp,
  Button as AntButton,
  Card as AntCard,
  Pagination as AntPagination,
  Select as AntSelect,
  Tabs as AntTabs,
  Tag,
} from "./antd";

type ClassValue = string | false | null | undefined;

/** Dependency-free class-name joiner for the Web compatibility components. */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function formatPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unit).toFixed(1)} ${units[unit]}`;
}

export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1))}…`;
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
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  type?: "button" | "submit" | "reset";
  asChild?: boolean;
}

const BUTTON_BASE =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4";
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
  destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
  outline: "border border-input bg-background/50 shadow-sm hover:bg-accent hover:text-accent-foreground",
  secondary: "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  link: "text-primary underline-offset-4 hover:underline",
  hero: "bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)] text-primary-foreground shadow-md",
};
const BUTTON_SIZES: Record<ButtonSize, string> = {
  default: "h-11 px-4 py-2 md:h-9",
  sm: "h-8 rounded-md px-3 text-xs",
  lg: "h-11 rounded-lg px-6 text-base",
  xl: "h-12 rounded-xl px-8 text-base",
  icon: "h-9 w-9 p-0",
};

/** AntD Button adapter with a dependency-free child-cloning path for router links. */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  variant = "default",
  size = "default",
  type = "button",
  asChild = false,
  className,
  children,
  disabled,
  onClick,
  style,
  ...props
}: ButtonProps, ref) {
  const buttonClassName = cn(
    BUTTON_BASE,
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    className,
  );

  if (asChild) {
    const child = React.Children.only(children);
    if (!React.isValidElement(child)) {
      throw new Error("Button with asChild requires one React element child.");
    }
    const childProps = child.props as {
      className?: string;
      onClick?: React.MouseEventHandler<HTMLElement>;
      style?: React.CSSProperties;
    };
    return React.cloneElement(
      child as React.ReactElement<Record<string, unknown>>,
      {
        ...props,
        ref,
        "aria-disabled": disabled || undefined,
        className: cn(buttonClassName, childProps.className),
        onClick: (event: React.MouseEvent<HTMLElement>) => {
          if (disabled) {
            event.preventDefault();
            return;
          }
          childProps.onClick?.(event);
          if (!event.defaultPrevented) {
            (onClick as unknown as React.MouseEventHandler<HTMLElement> | undefined)?.(event);
          }
        },
        style: { ...style, ...childProps.style },
      },
    );
  }

  const antType =
    variant === "ghost"
      ? "text"
      : variant === "link"
        ? "link"
        : variant === "default" || variant === "destructive" || variant === "hero"
          ? "primary"
          : "default";
  const antSize = size === "sm" ? "small" : size === "lg" || size === "xl" ? "large" : "middle";
  const antProps = props as unknown as React.ComponentProps<typeof AntButton>;
  return (
    <AntButton
      {...antProps}
      ref={(instance) => {
        const element = instance as HTMLButtonElement | null;
        if (typeof ref === "function") ref(element);
        else if (ref) ref.current = element;
      }}
      type={antType}
      htmlType={type}
      danger={variant === "destructive"}
      size={antSize}
      disabled={disabled}
      onClick={onClick as React.MouseEventHandler<HTMLElement> | undefined}
      style={style}
      className={buttonClassName}
    >
      {children}
    </AntButton>
  );
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
}

export function Badge({ variant = "default", className, children, style, ...props }: BadgeProps) {
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
      className={cn("inline-flex items-center rounded-full text-xs font-medium", className)}
      style={{ marginInlineEnd: 0, ...style }}
    >
      {children}
    </Tag>
  );
}

export function Card({ className, children, ...props }: React.ComponentProps<typeof AntCard>) {
  return (
    <AntCard
      {...props}
      className={cn(
        "group/card relative overflow-hidden border bg-card text-card-foreground shadow-sm",
        className,
      )}
      styles={{ body: { padding: 0 } }}
    >
      {children}
    </AntCard>
  );
}

export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex min-h-10 flex-col gap-1.5 border-b border-border/60 bg-muted/20 px-5 py-3",
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return <h3 className={cn("text-base font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("p-5 [&>*+*]:mt-2", className)} {...props} />;
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
          "h-11 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-primary disabled:opacity-50 md:h-9",
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

function selectOptions(
  children: React.ReactNode,
): Array<{ label: React.ReactNode; value: string; disabled?: boolean }> {
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
  return (
    <AntSelect
      id={triggerConfig?.id}
      className={triggerConfig?.className}
      style={{ width: "100%" }}
      value={value}
      defaultValue={defaultValue}
      disabled={disabled}
      placeholder={markerProps(valueMarker)?.placeholder}
      options={selectOptions(children)}
      onChange={(next) => onValueChange?.(String(next))}
    />
  );
}

interface TabsMarkerProps {
  children?: React.ReactNode;
  className?: string;
  value?: string;
  disabled?: boolean;
}

export function TabsList(_props: TabsMarkerProps) {
  return null;
}

export function TabsTrigger(_props: TabsMarkerProps) {
  return null;
}

export function TabsContent(_props: TabsMarkerProps) {
  return null;
}

function collectMarkers(children: React.ReactNode, type: React.ElementType): React.ReactElement[] {
  const markers: React.ReactElement[] = [];
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;
    if (child.type === type) {
      markers.push(child);
      return;
    }
    collectMarkers((child.props as TabsMarkerProps).children, type).forEach((marker) =>
      markers.push(marker),
    );
  });
  return markers;
}

export interface TabsProps {
  children: React.ReactNode;
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  className?: string;
}

/** Compound Tabs API rendered as AntD items while retaining content markers. */
export function Tabs({ children, value, defaultValue, onValueChange, className }: TabsProps) {
  const list = collectMarkers(children, TabsList)[0];
  const listProps = list?.props as TabsMarkerProps | undefined;
  const triggers = collectMarkers(listProps?.children, TabsTrigger);
  const contents = collectMarkers(children, TabsContent);
  const contentByValue = new Map(
    contents
      .map((content) => content.props as TabsMarkerProps)
      .filter((content): content is TabsMarkerProps & { value: string } => content.value !== undefined)
      .map((content) => [content.value, content]),
  );
  const items = triggers.flatMap((trigger) => {
    const triggerProps = trigger.props as TabsMarkerProps;
    if (triggerProps.value === undefined) return [];
    const content = contentByValue.get(triggerProps.value);
    return [{
      key: triggerProps.value,
      label: triggerProps.children,
      disabled: triggerProps.disabled,
      children: content ? <div className={content.className}>{content.children}</div> : undefined,
    }];
  });

  return (
    <AntTabs
      activeKey={value}
      defaultActiveKey={defaultValue}
      onChange={onValueChange}
      className={cn(className, listProps?.className)}
      items={items}
    />
  );
}

export function Table({ className, ...props }: React.ComponentProps<"table">) {
  return <table className={cn("w-full caption-bottom text-sm", className)} {...props} />;
}

export function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead className={cn("[&_tr]:border-b", className)} {...props} />;
}

export function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

export function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return <th className={cn("h-10 px-2 text-left align-middle font-medium", className)} {...props} />;
}

export function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return <tr className={cn("border-b transition-colors hover:bg-muted/50", className)} {...props} />;
}

export function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("p-2 align-middle", className)} {...props} />;
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
  totalPages,
  total,
  pageSize,
  onPageChange,
  disabled,
  label = "Pagination",
  className,
}: PaginationProps) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav
      aria-label={label}
      className={cn(
        "flex flex-col gap-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <span>{total === 0 ? "No items" : `${formatNumber(from)}–${formatNumber(to)} of ${formatNumber(total)}`}</span>
      {totalPages > 1 ? (
        <AntPagination
          current={page}
          total={total}
          pageSize={pageSize}
          showSizeChanger={false}
          disabled={disabled}
          onChange={onPageChange}
        />
      ) : null}
    </nav>
  );
}

export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("shimmer rounded-md", className)} {...props} />;
}

export type EmptyStateMode = "empty" | "filtered";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title?: string;
  description?: string;
  mode?: EmptyStateMode;
  action?: React.ReactNode;
  className?: string;
}

const EMPTY_COPY: Record<EmptyStateMode, { title: string; description: string }> = {
  empty: { title: "No data", description: "There are no records to display yet." },
  filtered: { title: "No results found", description: "Try adjusting your filters or search query." },
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  mode = "empty",
  action,
  className,
}: EmptyStateProps) {
  const copy = EMPTY_COPY[mode];
  const StateIcon = Icon ?? (mode === "filtered" ? SearchX : undefined);
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-muted/20 px-8 py-14 text-center",
        className,
      )}
      role="status"
    >
      {StateIcon ? (
        <div className="mb-5 flex size-14 items-center justify-center rounded-full bg-accent/50 text-accent-foreground/80">
          <StateIcon className="size-7" aria-hidden />
        </div>
      ) : null}
      <h3 className="font-display text-lg font-semibold tracking-tight">{title ?? copy.title}</h3>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
        {description ?? copy.description}
      </p>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export interface LoadingStateProps {
  label?: string;
  variant?: "skeleton" | "spinner";
  rows?: number;
  shape?: React.ReactNode;
  className?: string;
}

export function LoadingState({
  label = "Loading",
  variant = "skeleton",
  rows = 3,
  shape,
  className,
}: LoadingStateProps) {
  if (variant === "spinner") {
    return (
      <div role="status" aria-live="polite" className={cn("flex items-center justify-center gap-3 py-12 text-muted-foreground", className)}>
        <LoaderCircle className="size-5 animate-spin" aria-hidden />
        <span className="text-sm">{label}</span>
      </div>
    );
  }
  return (
    <div role="status" aria-live="polite" aria-label={label} className={cn("space-y-3 py-2", className)}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3">
          {shape ?? <Skeleton className="h-5 w-full" />}
        </div>
      ))}
    </div>
  );
}

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  retryLabel?: string;
  requestId?: string;
  icon?: LucideIcon;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  retryLabel = "Try again",
  requestId,
  icon: Icon = TriangleAlert,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-destructive/30 bg-destructive/5 px-8 py-12 text-center",
        className,
      )}
    >
      <div className="mb-4 flex size-14 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <Icon className="size-7" aria-hidden />
      </div>
      <h3 className="font-display text-lg font-semibold tracking-tight">{title}</h3>
      {message ? <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{message}</p> : null}
      {requestId ? <p className="mt-3 rounded-md border border-border bg-muted/50 px-2 py-1 font-mono text-[11px] text-muted-foreground">Request ID: {requestId}</p> : null}
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-5">
          <RotateCcw className="size-3.5" aria-hidden />
          {retryLabel}
        </Button>
      ) : null}
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
          <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
            {breadcrumb.map((item, index) => {
              const isLast = index === breadcrumb.length - 1;
              return (
                <li key={index} className="flex items-center gap-1.5">
                  {item.href && !isLast ? <a href={item.href}>{item.label}</a> : <span aria-current={isLast ? "page" : undefined}>{item.label}</span>}
                  {!isLast ? <ChevronRight className="size-3.5" aria-hidden /> : null}
                </li>
              );
            })}
          </ol>
        </nav>
      ) : breadcrumb ?? null}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3.5">
          {Icon ? (
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-primary shadow-sm">
              <Icon className="size-5" aria-hidden />
            </div>
          ) : null}
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">{title}</h1>
            {description ? <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2 lg:shrink-0">{actions}</div> : null}
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
    <Card className={cn("card-lift card-hover-accent group/stat", className)}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
          {icon}
        </div>
        <p className="mt-2 font-display text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
        {trend ? <p className={cn("mt-1.5 text-xs font-medium", trend.positive ? "text-emerald-600" : "text-red-500")}>{trend.positive ? "↑" : "↓"} {trend.value}</p> : null}
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
        "absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-card/80 backdrop-blur-sm transition-opacity duration-300",
        visible ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        className,
      )}
      role="status"
      aria-live="polite"
      aria-hidden={!visible}
    >
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <BarChart3 className="size-6 text-muted-foreground" aria-hidden />
      </div>
      <p className="text-sm font-semibold text-muted-foreground">{message}</p>
      {description ? <p className="max-w-xs text-center text-xs text-muted-foreground/70">{description}</p> : null}
    </div>
  );
});

export type ToastVariant = "success" | "error" | "info";
export type ToastPosition = "bottom-right" | "bottom-left" | "top-right" | "top-left";

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number | null;
}

export interface ToastContextValue {
  toast: (options: ToastOptions) => string;
  success: (title: string, description?: string, duration?: number | null) => string;
  error: (title: string, description?: string, duration?: number | null) => string;
  info: (title: string, description?: string, duration?: number | null) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

export interface ToastProviderProps {
  children: React.ReactNode;
  duration?: number;
  position?: ToastPosition;
  limit?: number;
  label?: string;
  className?: string;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function ToastProvider({ children, duration = 4000 }: ToastProviderProps) {
  const { message } = AntApp.useApp();
  const nextId = React.useRef(0);

  const push = React.useCallback(
    (options: ToastOptions) => {
      const id = `web-toast-${++nextId.current}`;
      const timeout = options.duration === undefined ? duration : options.duration;
      void message.open({
        key: id,
        type: options.variant ?? "info",
        duration: timeout === null ? 0 : timeout / 1000,
        content: (
          <div className="text-left">
            <div className="font-medium">{options.title}</div>
            {options.description ? <div className="text-xs opacity-75">{options.description}</div> : null}
          </div>
        ),
      });
      return id;
    },
    [duration, message],
  );

  const value = React.useMemo<ToastContextValue>(
    () => ({
      toast: push,
      success: (title, description, toastDuration) => push({ title, description, variant: "success", duration: toastDuration }),
      error: (title, description, toastDuration) => push({ title, description, variant: "error", duration: toastDuration }),
      info: (title, description, toastDuration) => push({ title, description, variant: "info", duration: toastDuration }),
      dismiss: (id) => message.destroy(id),
      dismissAll: () => message.destroy(),
    }),
    [message, push],
  );

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within a <ToastProvider>.");
  return context;
}
