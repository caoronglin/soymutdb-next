/**
 * BLAST — second-level catalog of the /search portal (PPTX V2 slide 6/7).
 * The full BLAST form lives at /blast; this page is an entry card that
 * links there.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button, Card, Typography } from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";
import { FadeUp } from "../../components/route-motion";

export const Route = createFileRoute("/search/blast")({
  component: SearchBlastComponent,
});

function SearchBlastComponent() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.blast.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.blast.subtitle")}
        </h2>

        <Card className="mt-6 max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <ThunderboltOutlined aria-hidden />
            </div>
            <Typography.Paragraph className="mb-0 leading-relaxed text-muted-foreground">
              {t("search.blast.desc")}
            </Typography.Paragraph>
          </div>
          <Button
            type="primary"
            className="mt-5"
            icon={<ThunderboltOutlined aria-hidden />}
            onClick={() => navigate({ to: "/blast" })}
          >
            {t("search.blast.open")}
          </Button>
        </Card>
      </div>
    </FadeUp>
  );
}
