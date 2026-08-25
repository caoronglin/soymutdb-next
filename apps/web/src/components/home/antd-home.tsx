/**
 * AntdHome — public home page matching docs/01.pptx slide 1 (real geometry).
 *
 * Actual layout (from the pptx shape coordinates):
 *   - top area: 最新动态 news list on the LEFT (~40%), a 滚动照片 photo
 *     carousel on the RIGHT (~60%);
 *   - bottom area: 收索工具 heading + the five first-level search-tool
 *     directory buttons (基因 ID / 物理位置 / Gbrowse / 引物设计 / BLAST) laid
 *     out horizontally, each linking to its second-level directory.
 *
 * Ant Design (v6) is the only UI library used here (`@/lib/antd` facade + the
 * official @ant-design/icons). Colours come from the design tokens exposed as
 * CSS variables (src/index.css), so the page follows light/dark mode.
 */
import * as React from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  ArrowRightOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  GlobalOutlined,
  IdcardOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Carousel,
  Col,
  Empty,
  Input,
  List,
  Row,
  Tag,
  Typography,
} from "@/lib/antd";
import { FluidGradient } from "../fluids/fluid-gradient";
import { useAnimation } from "@/lib/animation-context";
import { RenderNode } from "../../page-builder/renderer";
import type { PageComponentNode } from "@soymutdb/shared";

const { Title, Paragraph, Text } = Typography;

/** Science-green fluid palette for the hero photo carousel slides. */
const HERO_PALETTES: string[][] = [
  ["#052a1f", "#0d4a37", "#1b7a52", "#2f9e6b", "#0c3326"],
  ["#171a3a", "#1a3870", "#2d5f9e", "#4a8ac4", "#0d1f4a"],
  ["#0f2b1f", "#0d4a37", "#1b6b4a", "#3f8f65", "#0a2b1a"],
];

const HERO_SLIDES = [
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · MULTI-SPECIES",
    titleKey: "home.heroTitle",
    title: "探索大豆突变的未知疆域",
    subKey: "home.heroSubtitle",
    sub: "新一代多物种突变数据库，从基因组到表型一站探索。",
  },
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · MUTATION",
    titleKey: "home.heroSlide2",
    title: "从 20 条染色体到全局表型",
    subKey: "home.heroSlide2Desc",
    sub: "覆盖大豆参考基因组与突变集合，支持基因、位点、BLAST 多维检索。",
  },
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · JBROWSE 2",
    titleKey: "home.heroSlide3",
    title: "突变特征一览无余",
    subKey: "home.heroSlide3Desc",
    sub: "以表格与可视化呈现染色体、突变类型、基因位点与 JBrowse 2 跳转。",
  },
];

interface ToolEntry {
  key: string;
  labelKey: string;
  label: string;
  descKey: string;
  desc: string;
  route: string;
  icon: React.ReactNode;
}

// Slide 1 directory order: 基因 ID / 物理位置 / Gbrowse / 引物设计 / BLAST.
const TOOL_ENTRIES: ToolEntry[] = [
  { key: "gene", labelKey: "home.toolGeneLabel", label: "基因 ID 检索", descKey: "home.toolGeneDesc", desc: "按基因号查询突变", route: "/search/genes", icon: <IdcardOutlined /> },
  { key: "location", labelKey: "home.toolLocationLabel", label: "物理位置检索", descKey: "home.toolLocationDesc", desc: "按染色体与位点查询", route: "/search/location", icon: <EnvironmentOutlined /> },
  { key: "gbrowse", labelKey: "home.toolGbrowseLabel", label: "JBrowse 2", descKey: "home.toolGbrowseDesc", desc: "在 JBrowse 2 中浏览基因组", route: "/search/gbrowse", icon: <GlobalOutlined /> },
  { key: "primer", labelKey: "home.toolPrimerLabel", label: "引物设计", descKey: "home.toolPrimerDesc", desc: "设计并检查引物", route: "/search/primer", icon: <ExperimentOutlined /> },
  { key: "blast", labelKey: "home.toolBlastLabel", label: "BLAST 比对", descKey: "home.toolBlastDesc", desc: "序列比对检索同源", route: "/blast", icon: <ThunderboltOutlined /> },
];

const NEWS_PLACEHOLDER = [
  { id: "n1", titleKey: "home.news1", title: "SoyMutDB 0.1.0 正式上线" },
  { id: "n2", titleKey: "home.news2", title: "新增 Wm82.v4.0 参考基因组" },
  { id: "n3", titleKey: "home.news3", title: "新增变异与 BLAST 检索工具" },
  { id: "n4", titleKey: "home.news4", title: "基因组浏览器深链接改进" },
  { id: "n5", titleKey: "home.news5", title: "社区共建数据开放申请" },
];

export function AntdHome({ resourceCards }: { resourceCards?: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { reduced } = useAnimation();

  const goSearch = () => navigate({ to: "/search", search: { q: undefined } });
  const [heroQuery, setHeroQuery] = React.useState("");
  const runHeroSearch = (term: string) => navigate({ to: "/search", search: { q: term.trim() || undefined } });

  return (
    <div data-testid="antd-home">
      {/* ---------------------------------------------------------------- */}
      {/* HERO (独立区块): brand intro with search, above news + carousel.   */}
      {/* ---------------------------------------------------------------- */}
      <section style={{ position: "relative", overflow: "hidden" }}>
        <FluidGradient
          reduced={reduced}
          colors={HERO_PALETTES[0]}
          style={{ minHeight: 440, borderRadius: 0, background: "linear-gradient(135deg, #052a1f 0%, #0d4a37 55%, #1b7a52 100%)" }}
        >
          <div style={{ position: "relative", zIndex: 1, maxWidth: 1200, margin: "0 auto", padding: "clamp(48px, 7vw, 88px) 24px" }}>
            <Text style={{ color: "rgba(255,255,255,0.72)", letterSpacing: "0.16em", fontSize: 12, textTransform: "uppercase", fontWeight: 600 }}>
              {t("home.heroEyebrow", { defaultValue: "SOYMUTDB · MULTI-SPECIES" })}
            </Text>
            <Title level={1} style={{ color: "#fff", margin: "18px 0 14px", fontSize: "clamp(2rem, 5vw, 3.25rem)", lineHeight: 1.1, maxWidth: "20ch", textShadow: "0 2px 24px rgba(0,0,0,0.35)" }}>
              {t("home.heroTitle", { defaultValue: "探索大豆突变的未知疆域" })}
            </Title>
            <Paragraph style={{ color: "rgba(255,255,255,0.86)", fontSize: "clamp(1rem, 1.6vw, 1.15rem)", maxWidth: "58ch", lineHeight: 1.7 }}>
              {t("home.heroSubtitle", { defaultValue: "新一代多物种突变数据库，从基因组到表型一站探索。" })}
            </Paragraph>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 22, maxWidth: 720 }}>
              <Input
                size="large"
                value={heroQuery}
                onChange={(e) => setHeroQuery(e.target.value)}
                onPressEnter={() => runHeroSearch(heroQuery)}
                placeholder={t("home.searchPlaceholder", { defaultValue: "搜索基因 ID、染色体位点或突变…" })}
                prefix={<SearchOutlined style={{ color: "var(--muted-foreground)" }} />}
                style={{ flex: 1, minWidth: 220 }}
                aria-label={t("home.searchPlaceholder", { defaultValue: "搜索基因 ID、染色体位点或突变…" })}
              />
              <Button type="primary" size="large" onClick={() => runHeroSearch(heroQuery)}>
                {t("home.searchButton", { defaultValue: "搜索" })}
              </Button>
            </div>
            <div style={{ marginTop: 22 }}>
              <Button type="primary" size="large" onClick={goSearch} style={{ marginRight: 12 }}>
                {t("home.heroPrimary", { defaultValue: "开始探索" })} <ArrowRightOutlined />
              </Button>
              <Button size="large" style={{ background: "rgba(255,255,255,0.08)", borderColor: "rgba(255,255,255,0.35)", color: "#fff" }}>
                {t("home.heroSecondary", { defaultValue: "了解更多" })}
              </Button>
            </div>
          </div>
        </FluidGradient>
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* TOP: 最新动态 (left) + 滚动照片 carousel (right).                   */}
      {/* ---------------------------------------------------------------- */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 24px 24px" }}>
        <Row gutter={[32, 32]}>
          {/* Latest news — 5 titles linking to /news. */}
          <Col xs={24} lg={9}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
              <Title level={3} style={{ margin: 0, fontWeight: 700 }}>
                {t("home.latestNews", { defaultValue: "最新动态" })}
              </Title>
              <Link to="/news" search={{ category: undefined, page: undefined }} className="home-section-link" style={{ color: "var(--primary)", fontWeight: 500 }}>
                {t("home.openTool", { defaultValue: "进入" })} →
              </Link>
            </div>
            <Card style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)" }} styles={{ body: { padding: "4px 20px" } }}>
              <List
                dataSource={NEWS_PLACEHOLDER}
                split
                locale={{ emptyText: <Empty description={t("home.noNews", { defaultValue: "暂无新闻" })} /> }}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Link to="/news" search={{ category: undefined, page: undefined }} className="home-news-link" style={{ color: "var(--foreground)" }}>
                          {t(item.titleKey, { defaultValue: item.title })}
                        </Link>
                      }
                      description={<Tag color="green" style={{ margin: 0 }}>{t("home.newsMeta", { defaultValue: "最新发布 · SoyMutDB" })}</Tag>}
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>

          {/* Photo carousel (滚动照片) — 3-6 brand slides. */}
          <Col xs={24} lg={15}>
            <Carousel autoplay autoplaySpeed={5200} effect="fade">
              {HERO_SLIDES.map((slide, i) => (
                <div key={slide.titleKey}>
                  <FluidGradient
                    reduced={reduced}
                    colors={HERO_PALETTES[i % HERO_PALETTES.length]}
                    style={{ minHeight: 340, borderRadius: 20 }}
                  >
                    <div
                      style={{
                        position: "relative",
                        zIndex: 1,
                        padding: "clamp(28px, 4vw, 52px)",
                      }}
                    >
                      <Text style={{ color: "rgba(255,255,255,0.72)", letterSpacing: "0.16em", fontSize: 11, textTransform: "uppercase", fontWeight: 600 }}>
                        {t(slide.eyebrowKey, { defaultValue: slide.eyebrow })}
                      </Text>
                      <Title level={2} style={{ color: "#fff", margin: "14px 0 10px", lineHeight: 1.15, textShadow: "0 2px 20px rgba(0,0,0,0.3)" }}>
                        {t(slide.titleKey, { defaultValue: slide.title })}
                      </Title>
                      <Paragraph style={{ color: "rgba(255,255,255,0.86)", fontSize: 15, maxWidth: "52ch", lineHeight: 1.7 }}>
                        {t(slide.subKey, { defaultValue: slide.sub })}
                      </Paragraph>
                      <Button type="primary" onClick={goSearch} style={{ marginTop: 8 }}>
                        {t("home.heroPrimary", { defaultValue: "开始探索" })} <ArrowRightOutlined />
                      </Button>
                    </div>
                  </FluidGradient>
                </div>
              ))}
            </Carousel>
          </Col>
        </Row>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* BOTTOM: 收索工具 — five first-level directory buttons in a row.    */}
      {/* ---------------------------------------------------------------- */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 24px 80px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 18 }}>
          <Title level={3} style={{ margin: 0, fontWeight: 700 }}>
            {t("home.featuredTools", { defaultValue: "搜索工具" })}
          </Title>
          <Link to="/search" className="home-section-link" style={{ color: "var(--primary)", fontWeight: 500 }}>
            {t("home.openTool", { defaultValue: "进入" })} →
          </Link>
        </div>

        <Row gutter={[20, 20]}>
          {TOOL_ENTRIES.map((tool) => (
            <Col key={tool.key} xs={24} sm={12} lg={{ flex: 1 }}>
              <Link to={tool.route} style={{ display: "block", textDecoration: "none", height: "100%" }}>
                <Card
                  hoverable
                  style={{ height: "100%", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)" }}
                  styles={{ body: { padding: 18, height: "100%" } }}
                >
                  <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        width: 44,
                        height: 44,
                        borderRadius: "var(--radius-md)",
                        background: "var(--accent)",
                        color: "var(--accent-foreground)",
                        flex: "0 0 auto",
                      }}
                    >
                      {tool.icon}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <Text strong style={{ display: "block", fontSize: 15, color: "var(--foreground)" }}>
                        {t(tool.labelKey, { defaultValue: tool.label })}
                      </Text>
                      <Paragraph style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 13, lineHeight: 1.5 }}>
                        {t(tool.descKey, { defaultValue: tool.desc })}
                      </Paragraph>
                    </div>
                  </div>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      </div>

      {/* Resource guide is a published `resource_cards` component supplied by
          the page definition. The legacy static visual shell is retained only
          when an older published definition has not yet supplied this node. */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "8px 24px 88px" }}>
        {resourceCards ? <RenderNode node={resourceCards} /> : (
          <section data-testid="resource-cards-fallback">
            <Title level={3} style={{ margin: "0 0 18px", fontWeight: 700 }}>
              {t("home.resourceNav", { defaultValue: "资源导览" })}
            </Title>
            <Row gutter={[20, 20]}>
              {[
                { key: "downloads", route: "/downloads", label: "数据下载", desc: "下载参考基因组、变异与注释数据" },
                { key: "guide", route: "/guide", label: "使用指南", desc: "快速上手与检索帮助" },
                { key: "publications", route: "/publications", label: "文献 / 出版物", desc: "SoyMutDB 相关文献" },
              ].map((r) => (
                <Col key={r.key} xs={24} sm={12} lg={8}>
                  <Link to={r.route} style={{ display: "block", textDecoration: "none", height: "100%" }}>
                    <Card hoverable style={{ height: "100%", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)" }}>
                      <Text strong style={{ display: "block", fontSize: 15, color: "var(--foreground)" }}>{r.label}</Text>
                      <Paragraph style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 13, lineHeight: 1.5 }}>{r.desc}</Paragraph>
                    </Card>
                  </Link>
                </Col>
              ))}
            </Row>
          </section>
        )}
      </div>
    </div>
  );
}

export default AntdHome;
