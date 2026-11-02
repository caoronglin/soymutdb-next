import { ConfigProvider, theme as antdTheme, type ThemeConfig } from "antd";
import type { PropsWithChildren } from "react";

import { brandTokens } from "./design-tokens";
import type { EffectiveMotionMode } from "./motion-policy";

export {
  Affix,
  Alert,
  App,
  App as AntdApp,
  Avatar,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Carousel,
  Checkbox,
  ColorPicker,
  Collapse,
  Col,
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
  Menu,
  message,
  Modal,
  Pagination,
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
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  theme,
} from "antd";
export {
  DrawerForm,
  ModalForm,
  PageContainer,
  ProCard,
  ProDescriptions,
  ProForm,
  ProFormSelect,
  ProFormText,
  ProLayout,
  ProTable,
  StatisticCard,
} from "@ant-design/pro-components";

export const BRAND_PRIMARY_HEX = "#2f6f4f";
export const BRAND_PRIMARY_OKLCH = brandTokens.primary;
export const BRAND_PRIMARY_OKLCH_DARK = "oklch(0.55 0.14 152)";

export type { ThemeConfig };
export type { ProColumns } from "@ant-design/pro-components";
export type { FormProps } from "antd/es/form";
export type { InputRef } from "antd/es/input";
export type { MenuProps } from "antd/es/menu";
export type { ColumnsType as TableColumnsType, TableProps } from "antd/es/table";
export type { UploadFile, UploadProps } from "antd/es/upload";
export * from "./design-tokens";

export function createSoyMutdbTheme(dark = false): ThemeConfig {
  const primary = dark ? BRAND_PRIMARY_OKLCH_DARK : BRAND_PRIMARY_OKLCH;
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: BRAND_PRIMARY_HEX,
      colorInfo: BRAND_PRIMARY_HEX,
      colorLink: BRAND_PRIMARY_HEX,
      fontFamily: brandTokens.fontFamily,
      borderRadius: brandTokens.radius,
      fontSizeHeading1: 40,
      fontSizeHeading2: 30,
      fontSizeHeading3: 24,
      fontSizeHeading4: 20,
      fontSizeHeading5: 16,
    },
    components: {
      Button: { colorPrimary: primary },
      Tag: { colorPrimary: primary },
      Menu: { itemSelectedBg: primary, itemSelectedColor: "#fff" },
    },
  };
}

export interface SoyMutdbProviderProps extends PropsWithChildren {
  dark?: boolean;
  theme?: ThemeConfig;
}

export function SoyMutdbProvider({
  children,
  dark = false,
  theme,
}: SoyMutdbProviderProps) {
  const base = createSoyMutdbTheme(dark);
  const resolvedTheme: ThemeConfig = {
    ...base,
    ...theme,
    token: { ...base.token, ...theme?.token },
    components: { ...base.components, ...theme?.components },
  };

  return <ConfigProvider theme={resolvedTheme}>{children}</ConfigProvider>;
}

export {
  parseMotionPreference,
  resolveMotionDecision,
  type EffectiveMotionMode,
  type MotionDecision,
  type MotionPreference,
  type MotionSessionCeiling,
  type MotionSignals,
} from "./motion-policy";

/** Ant Design motion durations derived from the resolved mode. */
export interface MotionDurations {
  base: number;
  fast: number;
  mid: number;
  slow: number;
}

/**
 * Map an effective motion mode onto Ant Design's duration tokens.
 *
 * Ant Design derives every component transition from these four tokens, so
 * setting them once moves the whole console instead of hand-animating each
 * component. `off` zeroes them rather than removing the token, because
 * components still read `motionDurationBase` when computing their own.
 */
export function motionTokens(effective: EffectiveMotionMode): MotionDurations {
  switch (effective) {
    case "off":
      return { base: 0, fast: 0, mid: 0, slow: 0 };
    case "minimal":
      return { base: 0.06, fast: 0.1, mid: 0.12, slow: 0.16 };
    default:
      return { base: 0.2, fast: 0.16, mid: 0.24, slow: 0.3 };
  }
}
