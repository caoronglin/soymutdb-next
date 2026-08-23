/**
 * Help route — getting started, FAQ, and contact.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  DownOutlined as ChevronDown,
  MailOutlined as Mail,
  QuestionCircleOutlined as HelpCircle,
  ReadOutlined as BookOpen,
  RocketOutlined as Rocket,
} from "@ant-design/icons";
import { Card, Typography } from "@/lib/antd";
import { FadeUp, Stagger } from "../components/route-motion";
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

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("help.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("help.subtitle")}</h1>
      </FadeUp>

      <Stagger className="mt-10 grid gap-4 md:grid-cols-3">
        <Card className="card-lift">
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Rocket className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{t("help.gettingStarted")}</Typography.Title>
            <Typography.Text>Quick start guide for new users</Typography.Text>
          </div>
          <div>
            <ol className="list-decimal space-y-1.5 pl-4 text-sm text-muted-foreground">
              <li>Search for genes or variants using the top search bar</li>
              <li>Filter results by chromosome, type, or impact</li>
              <li>View details or open in the genome browser</li>
              <li>Download data or request seeds</li>
            </ol>
          </div>
        </Card>

        <Card className="card-lift">
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <BookOpen className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{t("help.documentation")}</Typography.Title>
            <Typography.Text>API reference and tutorials</Typography.Text>
          </div>
          <div>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              <li>· REST API v1 reference</li>
              <li>· JBrowse 2 configuration</li>
              <li>· BLAST usage guide</li>
            </ul>
          </div>
        </Card>

        <Card className="card-lift">
          <div>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Mail className="size-5" aria-hidden />
            </div>
            <Typography.Title className="mt-2 text-base">{t("help.contact")}</Typography.Title>
            <Typography.Text>Get support from the team</Typography.Text>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Email us at <span className="font-mono text-foreground">support@soymutdb.org</span> for questions about data access, technical issues, or collaboration.</p>
          </div>
        </Card>
      </Stagger>

      <FadeUp>
        <Card className="mt-8">
          <div>
            <Typography.Title className="flex items-center gap-2">
              <HelpCircle className="size-5 text-primary" aria-hidden />
              {t("help.faq")}
            </Typography.Title>
          </div>
          <div>
            <div className="divide-y">
              {FAQS.map((faq, i) => (
                <FaqItem key={i} q={faq.q} a={faq.a} />
              ))}
            </div>
          </div>
        </Card>
      </FadeUp>
    </div>
  );
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="py-4">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-4 text-left"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-medium">{q}</span>
        <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open ? <p className="mt-2 text-sm text-muted-foreground">{a}</p> : null}
    </div>
  );
}
