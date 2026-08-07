/**
 * Seed request route — seed application form with MTA agreement.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Sprout, Send } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Input, Textarea, Label, Button, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@soymutdb/ui";
import { FadeUp } from "../components/route-motion";
import { z } from "zod";

export const Route = createFileRoute("/seed-request")({
  component: SeedRequestComponent,
});

const schema = z.object({
  lineId: z.string().min(1, "Select a mutant line"),
  quantity: z.number().int().min(1, "Quantity must be at least 1").max(50, "Max 50 seeds per request"),
  institution: z.string().min(2, "Institution is required"),
  purpose: z.string().min(20, "Please describe your research purpose (min 20 chars)"),
  shippingAddress: z.string().min(10, "Shipping address is required"),
  mtaAgreed: z.boolean().refine((v) => v === true, { message: "You must agree to the MTA" }),
});

function SeedRequestComponent() {
  const { t } = useTranslation();
  const [form, setForm] = React.useState({
    lineId: "",
    quantity: "10",
    institution: "",
    purpose: "",
    shippingAddress: "",
    mtaAgreed: false as boolean,
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitted, setSubmitted] = React.useState(false);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = schema.safeParse({
      lineId: form.lineId,
      quantity: Number(form.quantity),
      institution: form.institution,
      purpose: form.purpose,
      shippingAddress: form.shippingAddress,
      mtaAgreed: form.mtaAgreed,
    });
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = String(issue.path[0] ?? "_");
        if (!fieldErrors[key]) fieldErrors[key] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    setSubmitted(true);
  };

  if (submitted) {
    return (
      <div className="container-prose section-rhythm">
        <Card className="mx-auto max-w-lg text-center">
          <CardContent className="p-10">
            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-primary/10">
              <Sprout className="size-6 text-primary" aria-hidden />
            </div>
            <h2 className="font-display text-2xl font-semibold">Request submitted</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Your seed request has been received. You'll receive a confirmation email shortly with a tracking number.
            </p>
            <Button className="mt-6" onClick={() => { setSubmitted(false); setForm({ lineId: "", quantity: "10", institution: "", purpose: "", shippingAddress: "", mtaAgreed: false }); }}>
              Submit another request
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("seeds.requestTitle")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("seeds.requestDesc")}</h1>
      </FadeUp>

      <Card className="mt-8 max-w-2xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sprout className="size-5 text-primary" aria-hidden />
            {t("seeds.requestTitle")}
          </CardTitle>
          <CardDescription>{t("seeds.requestDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="lineId">Mutant line</Label>
                <Select value={form.lineId} onValueChange={(v) => setForm((f) => ({ ...f, lineId: v }))}>
                  <SelectTrigger id="lineId"><SelectValue placeholder="Select line" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="EMS-001">EMS-001</SelectItem>
                    <SelectItem value="EMS-002">EMS-002</SelectItem>
                    <SelectItem value="CRISPR-001">CRISPR-001</SelectItem>
                    <SelectItem value="T-DNA-001">T-DNA-001</SelectItem>
                  </SelectContent>
                </Select>
                {errors.lineId ? <p className="text-xs text-destructive">{errors.lineId}</p> : null}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="quantity">{t("seeds.quantity")}</Label>
                <Input id="quantity" type="number" min={1} max={50} value={form.quantity} onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))} className="font-mono" />
                {errors.quantity ? <p className="text-xs text-destructive">{errors.quantity}</p> : null}
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="institution">{t("seeds.institution")}</Label>
              <Input id="institution" value={form.institution} onChange={(e) => setForm((f) => ({ ...f, institution: e.target.value }))} />
              {errors.institution ? <p className="text-xs text-destructive">{errors.institution}</p> : null}
            </div>

            <div className="grid gap-2">
              <Label htmlFor="purpose">{t("seeds.purpose")}</Label>
              <Textarea id="purpose" value={form.purpose} onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))} className="min-h-[100px]" />
              {errors.purpose ? <p className="text-xs text-destructive">{errors.purpose}</p> : null}
            </div>

            <div className="grid gap-2">
              <Label htmlFor="shippingAddress">Shipping address</Label>
              <Textarea id="shippingAddress" value={form.shippingAddress} onChange={(e) => setForm((f) => ({ ...f, shippingAddress: e.target.value }))} className="min-h-[80px]" />
              {errors.shippingAddress ? <p className="text-xs text-destructive">{errors.shippingAddress}</p> : null}
            </div>

            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm">
              <input
                type="checkbox"
                checked={form.mtaAgreed}
                onChange={(e) => setForm((f) => ({ ...f, mtaAgreed: e.target.checked }))}
                className="mt-0.5 size-4 rounded border-input"
              />
              <span className="text-muted-foreground">{t("seeds.mtaText")}</span>
            </label>
            {errors.mtaAgreed ? <p className="text-xs text-destructive">{errors.mtaAgreed}</p> : null}

            <Button type="submit" size="lg">
              <Send className="size-4" aria-hidden />
              {t("seeds.submitRequest")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
