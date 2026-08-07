/**
 * Help route — getting started, FAQ, and contact.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { HelpCircle, BookOpen, Mail, Rocket, ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@soymutdb/ui";
import { FadeUp, Stagger } from "../components/route-motion";
import * as React from "react";

export const Route = createFileRoute("/help")({
  component: HelpComponent,
});

const FAQS: ReadonlyArray<{ q: string; a: string }> = [
  { q: "How do I search for a gene?", a: "Use the search bar at the top of any page, or visit the Genes page to filter by chromosome, biotype, or keyword. Gene IDs follow the Glyma.01G000100 format." },
  { q: "How do I download variant data?", a: "Visit the Downloads page for pre-built VCF, GFF3, and FASTA files. For filtered exports, use the export button on the Variants page to submit an async export job." },
  { q: "Can I request mutant seeds?", a: "Yes. Registered users can submit seed requests via the Seed Request page. You will need to agree to the Material Transfer Agreement (MTA)." },
  { q: "How do I cite SoyMutDB?", a: "Please cite: Zhang Y, Li X, Wang H, et al. SoyMutDB: a comprehensive soybean mutant database. Plant Biotechnology Journal. 2025. DOI: 10.1111/pbi.70000" },
  { q: "What genome assembly is used?", a: "SoyMutDB uses the Wm82.a4.v1 assembly (Glycine max Williams 82). All coordinates refer to this assembly unless stated otherwise." },
  { q: "How often is the data updated?", a: "Major releases occur twice a year. The current release is v2.0 (June 2025). Check the News page for update announcements." },
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
          <CardHeader>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Rocket className="size-5" aria-hidden />
            </div>
            <CardTitle className="mt-2 text-base">{t("help.gettingStarted")}</CardTitle>
            <CardDescription>Quick start guide for new users</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-1.5 pl-4 text-sm text-muted-foreground">
              <li>Search for genes or variants using the top search bar</li>
              <li>Filter results by chromosome, type, or impact</li>
              <li>View details or open in the genome browser</li>
              <li>Download data or request seeds</li>
            </ol>
          </CardContent>
        </Card>

        <Card className="card-lift">
          <CardHeader>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <BookOpen className="size-5" aria-hidden />
            </div>
            <CardTitle className="mt-2 text-base">{t("help.documentation")}</CardTitle>
            <CardDescription>API reference and tutorials</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              <li>· REST API v1 reference</li>
              <li>· GraphQL schema</li>
              <li>· JBrowse 2 configuration</li>
              <li>· BLAST usage guide</li>
            </ul>
          </CardContent>
        </Card>

        <Card className="card-lift">
          <CardHeader>
            <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Mail className="size-5" aria-hidden />
            </div>
            <CardTitle className="mt-2 text-base">{t("help.contact")}</CardTitle>
            <CardDescription>Get support from the team</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">Email us at <span className="font-mono text-foreground">support@soymutdb.org</span> for questions about data access, technical issues, or collaboration.</p>
          </CardContent>
        </Card>
      </Stagger>

      <FadeUp>
        <Card className="mt-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <HelpCircle className="size-5 text-primary" aria-hidden />
              {t("help.faq")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="divide-y">
              {FAQS.map((faq, i) => (
                <FaqItem key={i} q={faq.q} a={faq.a} />
              ))}
            </div>
          </CardContent>
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
