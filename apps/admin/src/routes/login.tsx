import { LoginOutlined, LockOutlined, SafetyCertificateOutlined, ExclamationCircleOutlined, ArrowRightOutlined } from "@ant-design/icons";
import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { cn } from "../lib/cn";
import { Typography, Card, Button, Input } from "@/lib/antd";
import { ApiError } from "@soymutdb/api-client";
import { useAuth } from "../lib/auth-context";

/** Password strength evaluation result. */
interface StrengthInfo {
  score: 0 | 1 | 2 | 3 | 4;
  label: string;
  barClass: string;
  textClass: string;
}

/** Score the entered password in real time (0–4). */
function evaluateStrength(pw: string): StrengthInfo {
  if (!pw) {
    return {
      score: 0,
      label: "Enter a password",
      barClass: "bg-muted",
      textClass: "text-muted-foreground",
    };
  }
  let raw = 0;
  if (pw.length >= 8) raw++;
  if (pw.length >= 12) raw++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) raw++;
  if (/\d/.test(pw)) raw++;
  if (/[^A-Za-z0-9]/.test(pw)) raw++;
  const score = Math.min(raw, 4) as StrengthInfo["score"];
  const map: Record<number, Omit<StrengthInfo, "score">> = {
    0: { label: "Too short", barClass: "bg-destructive", textClass: "text-destructive" },
    1: { label: "Weak", barClass: "bg-destructive", textClass: "text-destructive" },
    2: { label: "Fair", barClass: "bg-amber-500", textClass: "text-amber-600" },
    3: { label: "Good", barClass: "bg-lime-500", textClass: "text-lime-600" },
    4: { label: "Strong", barClass: "bg-primary", textClass: "text-primary" },
  };
  return { score, ...map[score] };
}

/**
 * Admin login page — public route (no AdminLayout). Submits credentials via
 * the auth context and redirects to the dashboard on success.
 */
export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const strength = evaluateStrength(password);

  // If a session already exists, bounce to the dashboard.
  React.useEffect(() => {
    if (isAuthenticated) {
      void navigate({ to: "/" });
    }
  }, [isAuthenticated, navigate]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      await navigate({ to: "/" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid username or password.");
      } else if (err instanceof Error && err.message) {
        setError(err.message);
      } else {
        setError("Login failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm">
        {/* Brand header */}
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <SafetyCertificateOutlined className="size-6" />
          </div>
          <h1 className="font-serif text-2xl font-semibold">SoyMutDB Admin</h1>
          <p className="text-sm text-muted-foreground">
            Sign in to the management console
          </p>
        </div>

        <Card>
          <div>
            <Typography.Title level={5} className="flex items-center gap-2">
              <LoginOutlined className="size-4" />
              Sign in
            </Typography.Title>
            <Typography.Text type="secondary">
              Enter your administrator credentials to continue.
            </Typography.Text>
          </div>
          <form onSubmit={handleSubmit} noValidate>
            <div className="space-y-4">
              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
                >
                  <ExclamationCircleOutlined className="mt-0.5 size-4 shrink-0" />
                  <span>{error}</span>
                </div>
              ) : null}

              <div className="space-y-1.5">
                <label htmlFor="username">Username</label>
                <Input
                  id="username"
                  name="username"
                  type="text"
                  autoComplete="username"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  disabled={submitting}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password">Password</label>
                <div className="relative">
                  <LockOutlined
                    className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                    aria-hidden
                  />
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    disabled={submitting}
                    className="pl-9"
                  />
                </div>

                {/* Real-time password strength indicator */}
                <div className="space-y-1">
                  <div className="flex h-1.5 w-full gap-1" aria-hidden>
                    {[0, 1, 2, 3].map((i) => (
                      <div
                        key={i}
                        className={cn(
                          "h-full flex-1 rounded-full transition-colors",
                          i < strength.score ? strength.barClass : "bg-muted",
                        )}
                      />
                    ))}
                  </div>
                  <p className={cn("text-xs", strength.textClass)}>
                    {strength.label}
                  </p>
                </div>
              </div>
            </div>
            <div>
              <Button htmlType="submit" className="w-full" disabled={submitting}>
                {submitting ? (
                  "Signing in…"
                ) : (
                  <>
                    Sign in
                    <ArrowRightOutlined className="size-4" />
                  </>
                )}
              </Button>
            </div>
          </form>
        </Card>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Authorized personnel only.
        </p>
      </div>
    </div>
  );
}
