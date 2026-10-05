/**
 * Help route — getting started, FAQ, and contact.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  MailOutlined as Mail,
  QuestionCircleOutlined as HelpCircle,
  ReadOutlined as BookOpen,
  RocketOutlined as Rocket,
} from "@ant-design/icons";
import { Card, Collapse, Typography } from "@/lib/antd";
import { FadeUp, Stagger } from "../components/route-motion";
import { useSiteContent } from "../lib/site-content-react";
import * as React from "react";

export const Route = createFileRoute("/help")({
  component: HelpComponent,
});

const FAQS: ReadonlyArray<{ q: string; a: string }> = [
  { q: "How do I search for a gene?", a: "Use the search bar at the top of any page, or visit the Genes page to filter by chromosome, biotype, or keyword. Gene IDs follow the Glyma.01G000100 format." },
  { q: "How do I download variant data?", a: "Visit the Downloads page for the files currently published for a release. Check each item's format, assembly, release, and provenance metadata before using it in an analysis." },
  { q: "Can I request mutant seeds?", a: "Open the Seed Request page to see whether requests are currently enabled and to review the eligibility and distribution terms shown during submission." },
  { q: "How do I cite SoyMutDB?", a: "Use the citation and provenance metadata published with the exact data release you used. A journal citation or DOI is shown only after it has been verified by the project maintainers." },
  { q: "What genome assembly is used?", a: "The assembly is part of the search, record, browser, and download context. Confirm the displayed assembly before comparing or combining genomic coordinates." },
  { q: "How often is the data updated?", a: "Release versions and publication dates are announced on the News and Downloads pages. SoyMutDB does not promise a fixed release cadence on this Help page." },
];

function HelpComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("help.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("help.subtitle")}</h1>
      </FadeUp>

      <Stagger className="mt-10 grid gap-4 md:grid-cols-3">
        <Card className="flex h-full flex-col" styles={{ body: { display: "flex", flexDirection: "column", flex: 1 } }}>
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Rocket className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{get("help.gettingStarted", t("help.gettingStarted"))}</Typography.Title>
            <Typography.Text>{t("help.quickStartDesc")}</Typography.Text>
          </div>
          <div className="mt-4">
            <ol className="list-decimal space-y-1.5 pl-4 text-sm text-muted-foreground">
              <li>{t("help.stepSearch")}</li>
              <li>{t("help.stepFilter")}</li>
              <li>{t("help.stepDetails")}</li>
              <li>{t("help.stepDownload")}</li>
            </ol>
          </div>
        </Card>

        <Card className="flex h-full flex-col" styles={{ body: { display: "flex", flexDirection: "column", flex: 1 } }}>
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <BookOpen className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{get("help.documentation", t("help.documentation"))}</Typography.Title>
            <Typography.Text>{t("help.documentationDesc")}</Typography.Text>
          </div>
          <div className="mt-4">
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              <li>· {t("help.restApi")}</li>
              <li>· {t("help.jbrowseDocs")}</li>
              <li>· {t("help.blastDocs")}</li>
            </ul>
          </div>
        </Card>

        <Card className="flex h-full flex-col" styles={{ body: { display: "flex", flexDirection: "column", flex: 1 } }}>
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Mail className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{get("help.contact", t("help.contact"))}</Typography.Title>
            <Typography.Text>{t("help.contactDesc")}</Typography.Text>
          </div>
          <div className="mt-4">
            <p className="text-sm text-muted-foreground">{t("help.emailPrefix")} <span className="font-mono text-foreground">{t("help.supportEmail")}</span> {t("help.emailSuffix")}</p>
          </div>
        </Card>
      </Stagger>

      <FadeUp>
        <Card className="mt-8">
          <div>
            <Typography.Title className="flex items-center gap-2">
              <HelpCircle className="size-5 text-primary" aria-hidden />
              {get("help.faq", t("help.faq"))}
            </Typography.Title>
          </div>
          <div>
            <Collapse
              ghost
              items={FAQS.map((faq, i) => ({
                key: String(i),
                label: <span className="font-medium">{get(`help.faq${i + 1}.q`, faq.q)}</span>,
                children: (
                  <p className="text-sm text-muted-foreground">
                    {get(`help.faq${i + 1}.a`, faq.a)}
                  </p>
                ),
              }))}
            />
          </div>
        </Card>
      </FadeUp>
    </div>
  );
}

// The hand-rolled FAQ disclosure was replaced by antd's `Collapse`, which owns
// the expanded state, the chevron rotation and the transition.
