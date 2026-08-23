/**
 * Publications route — list of research publications citing SoyMutDB.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ExportOutlined as ExternalLink, ReadOutlined as BookOpen } from "@ant-design/icons";
import { Button, Card, Tag } from "@/lib/antd";
import { FadeUp, Stagger } from "../components/route-motion";

export const Route = createFileRoute("/publications")({
  component: PublicationsComponent,
});

interface Publication {
  title: string;
  authors: string;
  journal: string;
  year: number;
  doi: string;
}

const PUBLICATIONS: Publication[] = [
  {
    title: "SoyMutDB: a comprehensive soybean mutant database for functional genomics",
    authors: "Zhang Y, Li X, Wang H, et al.",
    journal: "Plant Biotechnology Journal",
    year: 2025,
    doi: "10.1111/pbi.70000",
  },
  {
    title: "Large-scale mutagenesis reveals flowering time regulation in soybean",
    authors: "Li X, Zhang Y, Chen R, et al.",
    journal: "Nature Communications",
    year: 2024,
    doi: "10.1038/s41467-024-49000-1",
  },
  {
    title: "CRISPR/Cas9-mediated editing of GmFT genes alters soybean flowering",
    authors: "Wang H, Liu J, Zhang Y, et al.",
    journal: "Journal of Experimental Botany",
    year: 2024,
    doi: "10.1093/jxb/erae001",
  },
];

function PublicationsComponent() {
  const { t } = useTranslation();

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("publications.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("publications.subtitle")}</h1>
      </FadeUp>

      <Stagger className="mt-10 grid gap-4">
        {PUBLICATIONS.map((pub) => (
          <Card key={pub.doi} className="card-lift">
            <div>
              <div className="flex items-start gap-4">
                <div className="hidden size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground sm:flex">
                  <BookOpen className="size-5" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="font-display text-lg font-semibold leading-snug">{pub.title}</h2>
                  <p className="mt-2 text-sm text-muted-foreground">{pub.authors}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <Tag className="font-mono">{pub.journal}</Tag>
                    <span className="font-mono text-muted-foreground">{pub.year}</span>
                    <span className="font-mono text-muted-foreground">DOI: {pub.doi}</span>
                  </div>
                </div>
                <Button
                  type="text"
                  className="shrink-0"
                  href={`https://doi.org/${pub.doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`View paper ${pub.doi}`}
                >
                  <ExternalLink className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </Stagger>
    </div>
  );
}
