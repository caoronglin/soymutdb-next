/**
 * A minimal double of the shared Ant Design 6 / ProComponents facade.
 *
 * The admin route tests need to assert on rendered output — an error region, a
 * confirmation dialog, a table row action — but the real facade drags in
 * ProTable's virtual list, `matchMedia` layout probes and portal-based
 * dropdowns, none of which are what those tests are about. This double keeps
 * the *shape* of the facade (same named exports, same call signatures) and
 * renders plain DOM.
 *
 * Everything the production code passes to a component is still rendered, so
 * an assertion exercises the route's own markup rather than the double:
 * `ProTable` calls each column's `render`, `DataTable`'s empty state is
 * rendered when the data source is empty, and `Modal` renders its footer.
 *
 * Usage:
 *
 *     vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));
 */
import * as React from "react";

type Props = Record<string, unknown> & { children?: React.ReactNode };

const testid = (props: Props) => props["data-testid"] as string | undefined;

/**
 * Every `message.*` call made through the double, in order.
 *
 * A route that has to report a failure to the operator can be asserted
 * against this list instead of against antd's own toast markup.
 */
export const messageCalls: Array<{ level: string; content: string }> = [];

function record(level: string) {
  return (content: React.ReactNode) => {
    messageCalls.push({ level, content: String(content) });
  };
}

const messageApi = {
  success: record("success"),
  error: record("error"),
  info: record("info"),
  warning: record("warning"),
  warn: record("warning"),
  loading: record("loading"),
  open: record("open"),
  destroy: () => undefined,
};

/* -------------------------------------------------------------------------- */
/* Layout                                                                     */
/* -------------------------------------------------------------------------- */

export const PageContainer = (props: Props) => (
  <section data-testid={testid(props)}>
    <h1>{props.title as React.ReactNode}</h1>
    {props.subTitle ? <p>{props.subTitle as React.ReactNode}</p> : null}
    {props.extra as React.ReactNode}
    {props.children}
  </section>
);

export const ProCard = (props: Props) => {
  if (props.hidden) return null;
  return (
    <div data-testid={testid(props)}>
      {props.title as React.ReactNode}
      {props.extra as React.ReactNode}
      {props.children}
    </div>
  );
};

export const Card = (props: Props) => (
  <div data-testid={testid(props)}>
    {props.cover as React.ReactNode}
    {props.children}
  </div>
);

export const Space = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
export const Flex = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
export const Divider = () => <hr />;
export const Affix = (props: Props) => <div>{props.children}</div>;
export const Avatar = (props: Props) => <span>{props.children}</span>;
export const Breadcrumb = (props: Props) => <nav>{props.children}</nav>;
export const Carousel = (props: Props) => <div>{props.children}</div>;
export const Collapse = (props: Props) => <div>{props.children}</div>;
export const List = (props: Props) => <ul>{props.children}</ul>;
export const Row = (props: Props) => <div>{props.children}</div>;
export const Col = (props: Props) => <div>{props.children}</div>;

/* -------------------------------------------------------------------------- */
/* Feedback                                                                   */
/* -------------------------------------------------------------------------- */

export const Alert = (props: Props) => (
  <div role="alert" data-testid={testid(props)}>
    {props.title as React.ReactNode}
    {props.description as React.ReactNode}
    {props.action as React.ReactNode}
  </div>
);

export const Result = (props: Props) => (
  <div data-testid={testid(props)}>
    {props.title as React.ReactNode}
    {props.subTitle as React.ReactNode}
    {props.extra as React.ReactNode}
  </div>
);

export const Empty = (props: Props) => <div data-testid={testid(props)}>{props.description as React.ReactNode}{props.children}</div>;

export const Skeleton = (props: Props) => <div data-testid={testid(props)} aria-busy="true" />;
Skeleton.Image = (props: Props) => <div data-testid={testid(props)} aria-busy="true" />;

export const Spin = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
export const Progress = (props: Props) => <div data-testid={testid(props)} role="progressbar" />;
export const Tooltip = (props: Props) => <span data-testid={testid(props)}>{props.children}</span>;
export const Popover = (props: Props) => <span data-testid={testid(props)}>{props.children}</span>;
export const Popconfirm = (props: Props) => <span data-testid={testid(props)}>{props.children}</span>;

/* -------------------------------------------------------------------------- */
/* Inputs                                                                     */
/* -------------------------------------------------------------------------- */

export const Button = (props: Props) => (
  <button
    type={(props.htmlType as string | undefined) ?? "button"}
    data-testid={testid(props)}
    data-danger={String(Boolean(props.danger))}
    aria-label={props["aria-label"] as string | undefined}
    title={props.title as string | undefined}
    disabled={Boolean(props.disabled) || Boolean(props.loading)}
    onClick={props.onClick as (() => void) | undefined}
  >
    {props.children}
  </button>
);

export const Input = (props: Props) => (
  <input
    data-testid={testid(props)}
    id={props.id as string | undefined}
    type={props.type as string | undefined}
    aria-label={props["aria-label"] as string | undefined}
    placeholder={props.placeholder as string | undefined}
    value={(props.value as string | number | undefined) ?? ""}
    disabled={Boolean(props.disabled)}
    onChange={props.onChange as ((event: React.ChangeEvent<HTMLInputElement>) => void) | undefined}
  />
);
Input.TextArea = (props: Props) => (
  <textarea
    data-testid={testid(props)}
    id={props.id as string | undefined}
    aria-label={props["aria-label"] as string | undefined}
    placeholder={props.placeholder as string | undefined}
    value={(props.value as string | number | undefined) ?? ""}
    disabled={Boolean(props.disabled)}
    onChange={props.onChange as ((event: React.ChangeEvent<HTMLTextAreaElement>) => void) | undefined}
  />
);

export const InputNumber = (props: Props) => (
  <input
    data-testid={testid(props)}
    type="number"
    value={(props.value as number | undefined) ?? ""}
    onChange={props.onChange as ((event: React.ChangeEvent<HTMLInputElement>) => void) | undefined}
  />
);

export const TextArea = Input.TextArea;

/**
 * A free-text input with suggestions, which is how the navigation editors use
 * it: the value is what the operator typed, the options are only hints.
 */
export const AutoComplete = (props: Props) => (
  <input
    data-testid={testid(props)}
    aria-label={props["aria-label"] as string | undefined}
    value={(props.value as string | undefined) ?? ""}
    placeholder={props.placeholder as string | undefined}
    onChange={(event) =>
      (props.onChange as ((value: string) => void) | undefined)?.(event.target.value)
    }
    onBlur={props.onBlur as ((event: React.FocusEvent<HTMLInputElement>) => void) | undefined}
  />
);

export const Select = (props: Props) => {
  const options = (props.options as Array<{ value: string; label: React.ReactNode; disabled?: boolean }> | undefined) ?? [];
  return (
    <select
      data-testid={testid(props)}
      id={props.id as string | undefined}
      aria-label={props["aria-label"] as string | undefined}
      value={(props.value as string | undefined) ?? ""}
      disabled={Boolean(props.disabled)}
      onChange={(event) => (props.onChange as ((value: string) => void) | undefined)?.(event.target.value)}
    >
      {props.placeholder ? <option value="">{props.placeholder as React.ReactNode}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
};

export const Switch = (props: Props) => (
  <input
    type="checkbox"
    data-testid={testid(props)}
    checked={Boolean(props.checked)}
    disabled={Boolean(props.disabled) || Boolean(props.loading)}
    onChange={(event) =>
      (props.onChange as ((checked: boolean, event?: unknown) => void) | undefined)?.(event.target.checked, event)
    }
  />
);

export const Checkbox = (props: Props) => (
  <input
    type="checkbox"
    data-testid={testid(props)}
    checked={Boolean(props.checked)}
    disabled={Boolean(props.disabled)}
    onChange={props.onChange as ((event: React.ChangeEvent<HTMLInputElement>) => void) | undefined}
  />
);

export const Radio = (props: Props) => (
  <input
    type="radio"
    data-testid={testid(props)}
    checked={Boolean(props.checked)}
    onChange={props.onChange as ((event: React.ChangeEvent<HTMLInputElement>) => void) | undefined}
  />
);

export const Segmented = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
export const DatePicker = (props: Props) => <input data-testid={testid(props)} />;
export const ColorPicker = (props: Props) => (
  <input
    type="text"
    data-testid={testid(props)}
    aria-label={props["aria-label"] as string | undefined}
    defaultValue={(props.value as string | undefined) ?? ""}
  />
);
export const Upload = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

/* -------------------------------------------------------------------------- */
/* Data display                                                               */
/* -------------------------------------------------------------------------- */

export const Badge = (props: Props) => (
  <span data-testid={testid(props)} data-color={props.color as string | undefined}>
    {props.children}
  </span>
);

export const Tag = (props: Props) => (
  <span data-testid={testid(props)} data-color={props.color as string | undefined}>
    {props.children}
  </span>
);

export const Statistic = (props: Props) => (
  <div data-testid={testid(props)}>
    <span>{props.title as React.ReactNode}</span>
    <span data-testid="statistic-value">{String(props.value ?? "")}</span>
  </div>
);

export const StatisticCard = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

export const Descriptions = (props: Props) => {
  const items = props.items as Array<{ key: string; label?: React.ReactNode; children?: React.ReactNode }> | undefined;
  return (
    <dl data-testid={testid(props)}>
      {items?.map((item) => (
        <React.Fragment key={item.key}>
          <dt>{item.label}</dt>
          <dd>{item.children}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
};

export const Table = (props: Props) => <table data-testid={testid(props)}>{props.children}</table>;
export const Tabs = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

export const Steps = (props: Props) => {
  const items = (props.items as Array<{ title?: React.ReactNode; description?: React.ReactNode }> | undefined) ?? [];
  return (
    <ol data-testid={testid(props)} data-current={String(props.current ?? 0)}>
      {items.map((item, index) => (
        <li key={index}>
          {item.title}
          {item.description ? <p>{item.description}</p> : null}
        </li>
      ))}
    </ol>
  );
};

export const Typography = {
  Title: (props: Props) => {
    const level = Number(props.level ?? 3);
    const Tag_ = `h${Math.min(6, Math.max(1, level))}` as "h1";
    return <Tag_ data-testid={testid(props)}>{props.children}</Tag_>;
  },
  Text: (props: Props) => (
    <span data-testid={testid(props)} data-text-type={props.type as string | undefined}>
      {props.children}
    </span>
  ),
  Paragraph: (props: Props) => <p data-testid={testid(props)}>{props.children}</p>,
};

export const Pagination = (props: Props) => (
  <div data-testid={testid(props)} data-current={String(props.current ?? "")} />
);

/* -------------------------------------------------------------------------- */
/* Overlays                                                                   */
/* -------------------------------------------------------------------------- */

export const Modal = (props: Props) => {
  if (props.open === false) return null;
  return (
    <div role="dialog" data-testid={testid(props)} onKeyDown={(event) => {
      if (event.key === "Escape" && props.keyboard !== false) (props.onCancel as (() => void) | undefined)?.();
    }}>
      {props.closable !== false ? <button type="button" aria-label="Close" onClick={props.onCancel as (() => void) | undefined}>×</button> : null}
      <div>{props.title as React.ReactNode}</div>
      {props.children}
      <div data-testid="modal-footer">{props.footer as React.ReactNode}</div>
    </div>
  );
};
Modal.confirm = () => undefined;

export const Drawer = (props: Props) => {
  if (props.open === false) return null;
  return (
    <div role="dialog" data-testid={testid(props)}>
      {props.children}
    </div>
  );
};

export const DrawerForm = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
export const ModalForm = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

export const ConfigProvider = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

export const Grid = { useBreakpoint: () => ({ lg: true, md: true, sm: true, xs: true, xl: true }) };

export const Layout = Object.assign(
  (props: Props) => <div data-testid={testid(props)}>{props.children}</div>,
  {
    Sider: (props: Props) => <aside data-testid={testid(props)}>{props.children}</aside>,
    Content: (props: Props) => <main data-testid={testid(props)}>{props.children}</main>,
    Header: (props: Props) => <header data-testid={testid(props)}>{props.children}</header>,
    Footer: (props: Props) => <footer data-testid={testid(props)}>{props.children}</footer>,
  },
);

export const Menu = (props: Props) => <nav data-testid={testid(props)}>{props.children}</nav>;

/* -------------------------------------------------------------------------- */
/* Forms                                                                      */
/* -------------------------------------------------------------------------- */

const FormRoot = (props: Props) => (
  <form
    data-testid={testid(props)}
    onSubmit={(event) => {
      event.preventDefault();
      (props.onFinish as ((values: unknown) => void) | undefined)?.({});
    }}
  >
    {props.children}
  </form>
);

const FormItem = (props: Props) => (
  <div data-testid={testid(props)}>
    {props.label ? <label>{props.label as React.ReactNode}</label> : null}
    {props.children}
  </div>
);

export const Form = Object.assign(FormRoot, {
  Item: FormItem,
  useForm: () => [
    {
      resetFields: () => undefined,
      getFieldValue: () => undefined,
      setFieldsValue: () => undefined,
      setFields: () => undefined,
    },
  ],
  // Fields the double never binds, so a watched value is always "nothing yet".
  // A component that dereferences it must therefore handle the empty case.
  useWatch: () => undefined,
});

export const ProForm = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;
ProForm.Item = FormItem;
export const ProFormText = (props: Props) => <input data-testid={testid(props)} />;
export const ProFormSelect = (props: Props) => <select data-testid={testid(props)} />;
export const ProDescriptions = (props: Props) => <div data-testid={testid(props)}>{props.children}</div>;

/* -------------------------------------------------------------------------- */
/* Tables                                                                     */
/* -------------------------------------------------------------------------- */

interface DoubleColumn {
  key?: string;
  dataIndex?: string;
  title?: React.ReactNode;
  render?: (value: unknown, row: Record<string, unknown>, index: number) => React.ReactNode;
}

/**
 * A table double that renders its header cells as well as its rows.
 *
 * The header is not decoration here: several admin tables carry their own
 * per-column controls (a switch, a field name, a drag handle) in `title`, so a
 * double that dropped titles would silently hide the controls the route tests
 * exist to exercise. `rowKey` accepts the function form antd supports, because a
 * row identified by something other than a single column is the case that made
 * the index fallback a real defect.
 */
export const ProTable = (props: Props) => {
  const columns = props.columns as DoubleColumn[] | undefined;
  const dataSource = props.dataSource as Array<Record<string, unknown>> | undefined;
  const rowKey = props.rowKey as string | ((row: Record<string, unknown>, index?: number) => React.Key) | undefined;
  const emptyText = (props.locale as { emptyText?: React.ReactNode } | undefined)?.emptyText;
  const keyFor = (row: Record<string, unknown>, index: number) =>
    typeof rowKey === "function" ? rowKey(row, index) : String(row[rowKey ?? "id"]);
  return (
    <table data-testid={testid(props)}>
      <thead>
        <tr>
          {columns?.map((column, columnIndex) => (
            <th key={column.key ?? columnIndex}>{column.title}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {!dataSource || dataSource.length === 0 ? (
          <tr>
            <td>{emptyText}</td>
          </tr>
        ) : (
          dataSource.map((row, index) => (
            <tr key={keyFor(row, index)}>
              {columns?.map((column, columnIndex) => (
                <td key={column.key ?? columnIndex}>
                  {column.render
                    ? column.render(row[column.dataIndex ?? column.key ?? ""], row, index)
                    : null}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
};

/* -------------------------------------------------------------------------- */
/* App context                                                                */
/* -------------------------------------------------------------------------- */

export const App = Object.assign(
  (props: Props) => <div data-testid={testid(props)}>{props.children}</div>,
  { useApp: () => ({ message: messageApi, modal: {}, notification: {} }) },
);

export const message = messageApi;

export const theme = {
  defaultAlgorithm: () => ({}),
  darkAlgorithm: () => ({}),
  useToken: () => ({ token: { colorPrimary: "#000" } }),
};
