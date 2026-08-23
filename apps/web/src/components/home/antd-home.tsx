/**
 * AntdHome — public home page rebuilt with Ant Design primitives.
 *
 * Layout follows docs/01.pptx slide 1: hero carousel (with the DeepSeek-style
 * fluid animation as the lead panel), a news list (max five items), and five
 * first-level search-tool buttons that link to the second-level search pages.
 *
 * Ant Design is the only UI library used here (`@/lib/antd` facade plus the
 * official @ant-design/icons). No Tailwind utilities, no lucide/react icons.
 */
import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  AimOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  IdcardOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Carousel,
  Col,
  Empty,
  List,
  Row,
  Typography,
} from "@/lib/antd";
import { FluidHero } from "../fluids/fluid-hero";

const { Title, Paragraph } = Typography;

interface ToolEntry {
  key: string;
  labelKey: string;
  label: string;
  descKey: string;
  desc: string;
  route: string;
  icon: React.ReactNode;
}

const TOOL_ENTRIES: ToolEntry[] = [
  {
    key: "gene",
    labelKey: "home.toolGeneLabel",
    label: "基因 ID 检索",
    descKey: "home.toolGeneDesc",
    desc: "按基因号查询突变",
    route: "/search/genes",
    icon: <IdcardOutlined />,
  },
  {
    key: "location",
    labelKey: "home.toolLocationLabel",
    label: "物理位置检索",
    descKey: "home.toolLocationDesc",
    desc: "按染色体与位点查询",
    route: "/search/location",
    icon: <EnvironmentOutlined />,
  },
  {
    key: "gbrowse",
    labelKey: "home.toolGbrowseLabel",
    label: "Gbrowse 浏览",
    descKey: "home.toolGbrowseDesc",
    desc: "基因组浏览器跳转",
    route: "/search/gbrowse",
    icon: <AimOutlined />,
  },
  {
    key: "blast",
    labelKey: "home.toolBlastLabel",
    label: "BLAST 比对",
    descKey: "home.toolBlastDesc",
    desc: "序列比对检索同源",
    route: "/blast",
    icon: <ThunderboltOutlined />,
  },
  {
    key: "primer",
    labelKey: "home.toolPrimerLabel",
    label: "引物设计",
    descKey: "home.toolPrimerDesc",
    desc: "设计并检查引物",
    route: "/search/primer",
    icon: <ExperimentOutlined />,
  },
];

const NEWS_PLACEHOLDER = [
  { id: "n1", titleKey: "home.news1" },
  { id: "n2", titleKey: "home.news2" },
  { id: "n3", titleKey: "home.news3" },
  { id: "n4", titleKey: "home.news4" },
  { id: "n5", titleKey: "home.news5" },
];

export function AntdHome() {
  const { t } = useTranslation();

  return (
    <div data-testid="antd-home">
      {/* Hero carousel — lead slide uses the fluid animation. */}
      <Carousel autoplay autoplaySpeed={4500} effect="fade" style={{ maxHeight: 620 }}>
        <div key="fluid">
          <FluidHero
            title={t("home.heroTitle", { defaultValue: "探索大豆突变的未知疆域" })}
            subtitle={t("home.heroSubtitle", {
              defaultValue: "新一代多物种突变数据库，从基因组到表型一站探索。",
            })}
            eyebrow={t("home.heroEyebrow", { defaultValue: "SOYMUTDB · MULTI-SPECIES" })}
            primaryLabel={t("home.heroPrimary", { defaultValue: "开始探索" })}
            secondaryLabel={t("home.heroSecondary", { defaultValue: "了解更多" })}
          />
        </div>
        <div key="panel-1">
          <div
            style={{
              minHeight: 420,
              display: "flex",
              alignItems: "flex-end",
              padding: "clamp(32px, 6vw, 72px)",
              background: "linear-gradient(140deg, #1A3870 0%, #2D5F9E 55%, #4A8AC4 100%)",
            }}
          >
            <div>
              <Title style={{ color: "#fff", margin: 0 }}>{t("home.heroSlide2", { defaultValue: "从 20 条染色体到全局表型" })}</Title>
              <Paragraph style={{ color: "rgba(255,255,255,0.85)", fontSize: 16, maxWidth: "52ch" }}>
                {t("home.heroSlide2Desc", { defaultValue: "覆盖大豆参考基因组与突变集合，支持基因、位点、BLAST 多维检索。" })}
              </Paragraph>
            </div>
          </div>
        </div>
        <div key="panel-2">
          <div
            style={{
              minHeight: 420,
              display: "flex",
              alignItems: "flex-end",
              padding: "clamp(32px, 6vw, 72px)",
              background: "linear-gradient(140deg, #0D1F4A 0%, #1A3870 50%, #2D5F9E 100%)",
            }}
          >
            <div>
              <Title style={{ color: "#fff", margin: 0 }}>{t("home.heroSlide3", { defaultValue: "突变特征一览无余" })}</Title>
              <Paragraph style={{ color: "rgba(255,255,255,0.85)", fontSize: 16, maxWidth: "52ch" }}>
                {t("home.heroSlide3Desc", { defaultValue: "以表格与可视化呈现染色体、突变类型、基因位点与 JBrowse 跳转。" })}
              </Paragraph>
            </div>
          </div>
        </div>
      </Carousel>

      {/* Five first-level search-tool buttons (link to second-level pages). */}
      <Row gutter={[16, 16]} style={{ marginTop: 40 }}>
        {TOOL_ENTRIES.map((tool) => (
          <Col key={tool.key} xs={24} sm={12} lg={8}>
            <Button
              type="primary"
              size="large"
              block
              icon={tool.icon}
              href={tool.route}
              style={{ height: 92, justifyContent: "flex-start", textAlign: "left", paddingInline: 22 }}
            >
              <span style={{ display: "block", lineHeight: 1.3 }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 16 }}>
                  {t(tool.labelKey, { defaultValue: tool.label })}
                </span>
                <span style={{ display: "block", fontSize: 13, opacity: 0.85 }}>
                  {t(tool.descKey, { defaultValue: tool.desc })}
                </span>
              </span>
            </Button>
          </Col>
        ))}
      </Row>

      {/* Latest news — up to five items. */}
      <List
        header={
          <Title level={4} style={{ margin: 0 }}>
            {t("home.latestNews", { defaultValue: "最新动态" })}
          </Title>
        }
        style={{ marginTop: 40 }}
        dataSource={NEWS_PLACEHOLDER}
        locale={{ emptyText: <Empty description={t("home.noNews", { defaultValue: "暂无新闻" })} /> }}
        renderItem={(item) => (
          <List.Item>
            <List.Item.Meta
              title={
                <Link to="/news" search={{ category: undefined, page: undefined }} style={{ color: "#3757a7" }}>
                  {t(item.titleKey)}
                </Link>
              }
              description={t("home.newsMeta", { defaultValue: "最新发布 · SoyMutDB" })}
            />
          </List.Item>
        )}
      />
    </div>
  );
}

export default AntdHome;
