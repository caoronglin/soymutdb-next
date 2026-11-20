import * as React from "react";
// Application imports go through the shared Ant Design 6 / ProComponents facade.
export {
  Affix,
  Alert,
  App,
  AutoComplete,
  Avatar,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Carousel,
  Checkbox,
  Col,
  Collapse,
  ColorPicker,
  ConfigProvider,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Dropdown,
  Empty,
  Flex,
  Form,
  Grid,
  Input,
  InputNumber,
  Layout,
  List,
  message,
  Modal,
  Pagination,
  DrawerForm,
  ModalForm,
  Menu,
  ProLayout,
  ProCard,
  ProDescriptions,
  ProForm,
  ProFormSelect,
  ProFormText,
  ProTable,
  StatisticCard,
  Popconfirm,
  Popover,
  Progress,
  Radio,
  Result,
  Row,
  Select,
  Skeleton,
  Segmented,
  Space,
  Spin,
  Statistic,
  Steps,
  Switch,
  Table,
  Tabs,
  Tag,
  theme,
  Tooltip,
  Typography,
  Upload,
} from "@soymutdb/ui-react";

// Named through an alias so the wrapper below can keep the public name.
import { PageContainer as ProPageContainer } from "@soymutdb/ui-react";
export type {
  FormProps,
  InputRef,
  MenuProps,
  TableColumnsType,
  TableProps,
  ThemeConfig,
  UploadFile,
  UploadProps,
  ProColumns,
} from "@soymutdb/ui-react";

/**
 * `PageContainer`, with its title exposed as a level-one heading.
 *
 * The console layout deliberately does not name the page: `PageContainer` is the
 * single owner of that name, so a second `<h1>` in the shell would duplicate it
 * (see `routes/__root.tsx`). But antd renders the title into a `<span
 * class="ant-page-header-heading-title">`, so a page had no heading element at
 * all -- a screen reader could not jump to it, and the audit measured `h1: 0`
 * on every console page.
 *
 * The fix is `role="heading" aria-level={1}` on the title node rather than
 * swapping the tag: the pro component always wraps the title in a `<span>`, and
 * `<span><h1>` is invalid markup. ARIA exposes the same structure to assistive
 * technology, and the visible design is untouched.
 */
export function PageContainer({
  title,
  ...rest
}: React.ComponentProps<typeof ProPageContainer>): React.ReactElement {
  // This module is `.ts`, so the heading node is built with createElement
  // rather than JSX.
  const heading =
    title === undefined || title === null || title === false
      ? title
      : React.createElement("span", { role: "heading", "aria-level": 1 }, title);
  return React.createElement(ProPageContainer, { ...rest, title: heading });
}
