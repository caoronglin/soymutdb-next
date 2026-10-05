/**
 * Login route — standalone full-page authentication screen.
 *
 * Deliberately decoupled from the public portal chrome (no site header/footer):
 * the root layout renders /login without the SiteHeader/SiteFooter wrappers.
 * The public site exposes no login entry; users reach this page only via the
 * direct /login URL or via the API client's 401 redirect (/?redirect=…).
 *
 * Visual design: split-screen — left brand panel in primary green with a
 * chromosome ideogram motif; right form panel with the sign-in card.
 */
import * as React from "react";
import { createFileRoute, Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  AimOutlined as Microscope,
  ArrowLeftOutlined as ArrowLeft,
  ArrowRightOutlined as ArrowRight,
  BarChartOutlined as BarChart3,
  ClockCircleOutlined as Clock,
  DeploymentUnitOutlined as Dna,
  LockOutlined as Lock,
  LoginOutlined as LogIn,
  SafetyCertificateOutlined as ShieldCheck,
} from "@ant-design/icons";
import { Button, Card, Input, Typography } from "@/lib/antd";
import { ApiError, request, setAccessToken } from "@soymutdb/api-client";
import { TextReveal, Reveal, Stagger } from "../components/route-motion";

export const Route = createFileRoute("/login")({
  component: LoginComponent,
});

interface LoginResponse {
  access_token: string;
}

function safeRedirect(value: unknown): string {
  const containsControlCharacter =
    typeof value === "string" && Array.from(value).some((character) => character.charCodeAt(0) < 0x20);
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    containsControlCharacter
  ) {
    return "/";
  }
  return value;
}

function LoginComponent() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const search = useRouterState({ select: (s) => s.location.search });
  const redirectRaw =
    typeof search === "object" && search !== null
      ? (search as unknown as { redirect?: unknown }).redirect
      : undefined;
  const redirect = safeRedirect(redirectRaw);

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [submissionError, setSubmissionError] = React.useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setSubmissionError(null);

    try {
      // Login is deliberately a raw request, not `http.post`: a failed login
      // must not attempt a cookie refresh or emit a global logout event.
      // `withCredentials` accepts the HttpOnly refresh cookie; the access
      // token remains in module memory via `setAccessToken`.
      const session = await request<LoginResponse>("/auth/login", {
        method: "POST",
        json: { email: email.trim(), password },
        auth: false,
        withCredentials: true,
      });
      if (!session.access_token) throw new Error("Login response omitted access token");

      setAccessToken(session.access_token);
      // A previous anonymous /auth/me result must not remain visible after
      // navigation; the next consumer refetches with the new access token.
      queryClient.removeQueries({ queryKey: ["current-user"], exact: true });
      await navigate({ to: redirect });
    } catch (error) {
      setSubmissionError(
        error instanceof ApiError && (error.status === 401 || error.status === 403)
          ? t("loginPage.invalidCredentials")
          : t("loginPage.loginUnavailable"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* --------------------------------------------------------------- Brand panel */}
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-primary p-12 text-primary-foreground lg:flex">
        {/* Decorative chromosome ideogram motif */}
        <div className="pointer-events-none absolute inset-0 opacity-[0.18]" aria-hidden>
          <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 gap-3">
            {Array.from({ length: 10 }).map((_, i) => (
              <span
                key={i}
                className="block w-2 rounded-full bg-primary-foreground"
                style={{ height: `${120 + ((i * 37) % 180)}px` }}
              />
            ))}
          </div>
        </div>
        <div className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-primary-foreground/10 blur-3xl" aria-hidden />

        {/* Logo */}
        <Link to="/" className="relative flex items-center gap-2 self-start outline-none focus-visible:ring-2 focus-visible:ring-primary-foreground">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary-foreground/15">
            <Dna className="size-5" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            {t("brand.soy")}<span className="text-primary-foreground/70">{t("brand.mut")}</span>{t("brand.db")}
          </span>
        </Link>

        {/* Headline */}
        <div className="relative max-w-md">
          <TextReveal
            text={t("loginPage.brandTitle")}
            as="span"
            className="block font-display text-4xl font-semibold leading-[1.1] tracking-tight"
            step={40}
          />
          <Reveal variant="fade-up" delay={300} as="p" className="mt-5 text-base leading-relaxed text-primary-foreground/80">
            {t("loginPage.brandTagline")}
          </Reveal>
          <Stagger className="mt-8 flex flex-col gap-3" baseDelay={500} step={80}>
            {BRAND_BULLETS.map((b) => {
              const Icon = b.icon;
              return (
                <div key={b.key} className="flex items-center gap-3 text-sm text-primary-foreground/90">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/15">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  {t(`loginPage.brandBullets.${b.key}`)}
                </div>
              );
            })}
          </Stagger>
        </div>

        {/* Secure notes */}
        <ul className="relative flex flex-col gap-2 text-xs text-primary-foreground/70">
          {SECURE_NOTES.map((n) => {
            const Icon = n.icon;
            return (
              <li key={n.key} className="flex items-center gap-2">
                <Icon className="size-3.5" aria-hidden />
                {t(`loginPage.${n.key}`)}
              </li>
            );
          })}
        </ul>
      </aside>

      {/* --------------------------------------------------------------- Form panel */}
      <main className="flex flex-col bg-background">
        {/* Mobile logo */}
        <div className="flex items-center justify-between p-6 lg:hidden">
          <Link to="/" className="flex items-center gap-2" aria-label={t("common.home")}>
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Dna className="size-5" aria-hidden />
            </span>
            <span className="font-display text-lg font-semibold tracking-tight">
              {t("brand.soy")}<span className="text-primary">{t("brand.mut")}</span>{t("brand.db")}
            </span>
          </Link>
          <Link
            to="/"
            className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t("loginPage.backHome")}
          </Link>
        </div>

        <div className="flex flex-1 items-center justify-center px-6 py-10">
          <Reveal variant="blur-up" className="w-full max-w-md">
            <Card className="border-border/80 shadow-sm">
              <div>
                <p className="eyebrow">{t("loginPage.welcomeBack")}</p>
                <Typography.Title className="flex items-center gap-2">
                  <LogIn className="size-5 text-primary" aria-hidden />
                  {t("loginPage.title")}
                </Typography.Title>
              </div>
              <div className="p-8">
                <p className="text-sm text-muted-foreground">{t("loginPage.subtitle")}</p>

                <form className="mt-7 grid gap-5" onSubmit={onSubmit}>
                  <div className="grid gap-2">
                    <label htmlFor="email">{t("auth.email")}</label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder={t("loginPage.emailPlaceholder")}
                    />
                  </div>
                  <div className="grid gap-2">
                    <label htmlFor="password">{t("auth.password")}</label>
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>

                  {submissionError ? (
                    <p role="alert" className="text-sm text-destructive">
                      {submissionError}
                    </p>
                  ) : null}

                  <Button
                    htmlType="submit" type="primary"
                    size="large"
                    disabled={submitting}
                    aria-busy={submitting}
                    className="w-full"
                  >
                    {submitting ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="size-4 animate-spin rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground" aria-hidden />
                        {t("common.loading")}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        {t("auth.loginButton")}
                        <ArrowRight className="size-4" aria-hidden />
                      </span>
                    )}
                  </Button>

                  <p className="flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
                    <ShieldCheck className="size-3.5" aria-hidden />
                    {t("loginPage.redirectNotice")}
                  </p>
                </form>

                <div className="mt-6 flex flex-col gap-2 border-t pt-5 text-xs text-muted-foreground">
                  <p className="flex items-center gap-1.5">
                    <Lock className="size-3.5" aria-hidden />
                    {t("loginPage.secureNote")}
                  </p>
                  <p className="flex items-center gap-1.5">
                    <Clock className="size-3.5" aria-hidden />
                    {t("loginPage.sessionNote")}
                  </p>
                  <p className="flex items-center gap-1.5">
                    <Dna className="size-3.5" aria-hidden />
                    {t("loginPage.adminHint")}
                  </p>
                </div>
              </div>
            </Card>

            <p className="mt-6 text-center text-sm text-muted-foreground">
              <Link to="/" className="link-underline inline-flex items-center gap-1.5 font-medium text-foreground">
                <ArrowLeft className="size-4" aria-hidden />
                {t("loginPage.backHome")}
              </Link>
            </p>
          </Reveal>
        </div>
      </main>
    </div>
  );
}

const BRAND_BULLETS: ReadonlyArray<{ key: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "variants", icon: Dna },
  { key: "browser", icon: Microscope },
  { key: "analytics", icon: BarChart3 },
];

const SECURE_NOTES: ReadonlyArray<{ key: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "secureNote", icon: Lock },
  { key: "twoFactorHint", icon: ShieldCheck },
  { key: "sessionNote", icon: Clock },
];
