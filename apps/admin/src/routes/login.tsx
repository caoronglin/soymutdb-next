/**
 * Admin login page — public route (no AdminLayout). Submits credentials via
 * the auth context and redirects to the dashboard on success.
 *
 * Structurally aligned with the Ant Design CLI `Form / Login Form` demo
 * (`antd demo Form login`): every field is a `Form.Item`, the password uses
 * `Input.Password`, input prefixes go through `Input prefix=`, and the submit
 * button lives inside its own `Form.Item` so antd owns the 24px vertical
 * rhythm.
 *
 * Why this was rewritten: the previous revision wrapped only the error banner
 * and the two fields in a Tailwind `space-y-4` container and left the submit
 * button in a sibling `<div>`. The button therefore received no top margin and
 * overlapped the password-strength readout. Spacing now comes entirely from
 * antd tokens, per `antd design.md` ("snap every gap, inset, and gutter to the
 * 4px grid through the spacing scale", "don't use magic numbers").
 */
import {
  ArrowRightOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Alert, Button, Flex, Form, Input, Progress, Typography, theme } from "@/lib/antd";
import { ApiError } from "@soymutdb/api-client";
import { useAuth } from "../lib/auth-context";

/** Semantic strength tier; resolved to an antd colour token at render time. */
type StrengthTier = "neutral" | "error" | "warning" | "success";

interface StrengthInfo {
  /** 0, 25, 50, 75 or 100 — one step per scoring point. */
  percent: number;
  tier: StrengthTier;
  label: string;
}

type StrengthTranslate = (key: string, defaultValue: string) => string;

/**
 * Score the entered password in real time. The scoring rules are unchanged
 * from the original implementation; only the presentation moved to antd.
 */
function evaluateStrength(pw: string, t: StrengthTranslate): StrengthInfo {
  if (!pw) {
    return {
      percent: 0,
      tier: "neutral",
      label: t("admin.login.enterPassword", "Enter a password"),
    };
  }
  let raw = 0;
  if (pw.length >= 8) raw++;
  if (pw.length >= 12) raw++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) raw++;
  if (/\d/.test(pw)) raw++;
  if (/[^A-Za-z0-9]/.test(pw)) raw++;
  const score = Math.min(raw, 4);
  const tiers: Record<number, [StrengthTier, string]> = {
    0: ["error", t("admin.login.tooShort", "Too short")],
    1: ["error", t("admin.login.weak", "Weak")],
    2: ["warning", t("admin.login.fair", "Fair")],
    3: ["success", t("admin.login.good", "Good")],
    4: ["success", t("admin.login.strong", "Strong")],
  };
  const [tier, label] = tiers[score];
  return { percent: score * 25, tier, label };
}

interface LoginFormValues {
  username: string;
  password: string;
}

export default function LoginPage() {
  const { t } = useTranslation();
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [form] = Form.useForm<LoginFormValues>();

  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const password = Form.useWatch("password", form) ?? "";
  const strength = React.useMemo(
    () => evaluateStrength(password, (key, defaultValue) => t(key, { defaultValue })),
    [password, t],
  );

  const strengthColor = React.useMemo(() => {
    switch (strength.tier) {
      case "error":
        return token.colorError;
      case "warning":
        return token.colorWarning;
      case "success":
        return token.colorSuccess;
      default:
        return token.colorTextTertiary;
    }
  }, [strength.tier, token]);

  // If a session already exists, bounce to the dashboard.
  React.useEffect(() => {
    if (isAuthenticated) {
      void navigate({ to: "/" });
    }
  }, [isAuthenticated, navigate]);

  async function handleFinish(values: LoginFormValues) {
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(values.username.trim(), values.password);
      await navigate({ to: "/" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(
          t("admin.login.invalidCredentials", { defaultValue: "Invalid username or password." }),
        );
      } else if (err instanceof Error && err.message) {
        setError(err.message);
      } else {
        setError(t("admin.login.failed", { defaultValue: "Login failed. Please try again." }));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // Ant Design Pro presents sign-in as two panels: an identity panel and a
    // form panel. The former console stacked everything in one centred card on
    // a flat field, so the page carried no hierarchy and no product context
    // before the operator typed anything.
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        background: token.colorBgLayout,
      }}
    >
      <div
        // Decorative: every word here is repeated in the form panel beside it,
        // so a screen reader gains nothing from it. Hidden below the tablet
        // breakpoint by `index.css` so the fixed-width form panel never forces a
        // horizontal scrollbar on a phone.
        aria-hidden
        className="admin-login-hero"
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          flex: "1 1 55%",
          padding: `${token.paddingXL}px ${token.paddingXL * 1.5}px`,
          color: token.colorTextLightSolid,
          background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
        }}
      >
        <Flex align="center" gap={token.marginSM}>
          <SafetyCertificateOutlined style={{ fontSize: 28 }} />
          <span style={{ fontSize: 20, fontWeight: 600 }}>
            {t("admin.login.brandTitle", { defaultValue: "SoyMutDB Admin" })}
          </span>
        </Flex>

        <div style={{ maxWidth: 420 }}>
          <Typography.Title
            level={1}
            style={{ color: token.colorTextLightSolid, marginBottom: token.marginSM }}
          >
            {t("admin.login.heroTitle", {
              defaultValue: "Manage the soybean mutation database",
            })}
          </Typography.Title>
          <Typography.Paragraph
            style={{ color: token.colorTextLightSolid, opacity: 0.85, marginBottom: 0 }}
          >
            {t("admin.login.heroBody", {
              defaultValue:
                "Import variants, publish releases and curate site content from one console.",
            })}
          </Typography.Paragraph>
        </div>

        <Typography.Text style={{ color: token.colorTextLightSolid, opacity: 0.7 }}>
          {t("admin.login.authorizedOnly", { defaultValue: "Authorized personnel only." })}
        </Typography.Text>
      </div>

      <div
        className="admin-login-panel"
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          flex: "0 0 480px",
          maxWidth: "100%",
          padding: `${token.paddingXL}px ${token.paddingXL * 1.5}px`,
          background: token.colorBgContainer,
          borderInlineStart: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Typography.Title level={2} style={{ marginTop: 0, marginBottom: token.marginXS }}>
          {t("admin.login.signIn", { defaultValue: "Sign in" })}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: token.marginLG }}>
          {t("admin.login.enterCredentials", {
            defaultValue: "Enter your administrator credentials to continue.",
          })}
        </Typography.Paragraph>

            <Form<LoginFormValues>
              form={form}
              name="login"
              layout="vertical"
              requiredMark={false}
              disabled={submitting}
              onFinish={handleFinish}
              initialValues={{ username: "", password: "" }}
            >
              {error ? (
                <Form.Item>
                  <Alert type="error" showIcon title={error} />
                </Form.Item>
              ) : null}

              <Form.Item
                name="username"
                label={t("admin.login.username", { defaultValue: "Username" })}
                rules={[
                  {
                    required: true,
                    message: t("admin.login.usernameRequired", {
                      defaultValue: "Please enter your username",
                    }),
                  },
                ]}
              >
                <Input
                  data-testid="admin-identifier"
                  prefix={<UserOutlined />}
                  autoComplete="username"
                  placeholder="admin"
                  size="large"
                />
              </Form.Item>

              <Form.Item
                name="password"
                label={t("admin.login.password", { defaultValue: "Password" })}
                rules={[
                  {
                    required: true,
                    message: t("admin.login.passwordRequired", {
                      defaultValue: "Please enter your password",
                    }),
                  },
                ]}
                extra={
                  <Flex vertical gap={token.marginXS}>
                    <Progress
                      percent={strength.percent}
                      showInfo={false}
                      size="small"
                      strokeColor={strengthColor}
                      railColor={token.colorFillSecondary}
                      aria-label={strength.label}
                    />
                    <Typography.Text style={{ color: strengthColor, fontSize: token.fontSizeSM }}>
                      {strength.label}
                    </Typography.Text>
                  </Flex>
                }
              >
                <Input.Password
                  data-testid="admin-password"
                  prefix={<LockOutlined />}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  size="large"
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  block
                  type="primary"
                  size="large"
                  htmlType="submit"
                  loading={submitting}
                  data-testid="admin-login-submit"
                >
                  {submitting ? (
                    t("admin.login.signingIn", { defaultValue: "Signing in…" })
                  ) : (
                    <Flex align="center" justify="center" gap={token.marginXS}>
                      {t("admin.login.signIn", { defaultValue: "Sign in" })}
                      <ArrowRightOutlined />
                    </Flex>
                  )}
                </Button>
              </Form.Item>
            </Form>
      </div>
    </div>
  );
}
