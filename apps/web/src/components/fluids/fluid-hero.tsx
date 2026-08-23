/**
 * FluidHero — a full-bleed animated hero built from Ant Design primitives.
 *
 * Uses Ant Design `Typography` and `Button` for all chrome (no Tailwind / icon
 * library), and layers the self-contained `FluidGradient` WebGL canvas as the
 * animated background. Honors the app motion policy: when reduced-motion is on
 * the fluid renders a single static frame.
 */
import * as React from "react";
import { Button, Space, Typography } from "@/lib/antd";
import { useAnimation } from "@/lib/animation-context";
import { FluidGradient, type FluidGradientProps } from "./fluid-gradient";

const { Title, Paragraph, Text } = Typography;

export interface FluidHeroProps {
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  primaryLabel?: string;
  secondaryLabel?: string;
  onPrimary?: () => void;
  onSecondary?: () => void;
  gradientProps?: Partial<Omit<FluidGradientProps, "children" | "reduced">>;
  className?: string;
}

export function FluidHero({
  title = "Into the Unknown",
  subtitle = "DeepSeek 风格的流畅流体渐变，已作为项目前端真实组件接入。",
  eyebrow = "SOYMUTDB · NEW FRONTIER",
  primaryLabel = "开始探索",
  secondaryLabel = "了解更多",
  onPrimary,
  onSecondary,
  gradientProps,
  className,
}: FluidHeroProps) {
  const { reduced } = useAnimation();

  return (
    <section className={className} aria-label="featured hero">
      <FluidGradient
        reduced={reduced}
        {...gradientProps}
        style={{ minHeight: 420, borderRadius: 20, ...gradientProps?.style }}
      >
        <div style={{ padding: "clamp(32px, 6vw, 72px)" }}>
          <Text style={{ color: "rgba(255,255,255,0.68)", letterSpacing: "0.14em", fontSize: 12, textTransform: "uppercase" }}>
            {eyebrow}
          </Text>
          <Title style={{ color: "#fff", margin: "18px 0 14px", textShadow: "0 2px 18px rgba(10,26,58,0.45)", maxWidth: "18ch" }}>
            {title}
          </Title>
          <Paragraph style={{ color: "rgba(255,255,255,0.82)", fontSize: 16, maxWidth: "52ch", lineHeight: 1.7 }}>
            {subtitle}
          </Paragraph>
          <Space size="middle" style={{ marginTop: 8 }}>
            <Button type="primary" size="large" onClick={onPrimary}>
              {primaryLabel}
            </Button>
            <Button ghost size="large" onClick={onSecondary}>
              {secondaryLabel}
            </Button>
          </Space>
        </div>
      </FluidGradient>
    </section>
  );
}

export default FluidHero;
