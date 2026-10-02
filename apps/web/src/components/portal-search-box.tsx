/**
 * PortalSearchBox — the single identifier search entry.
 *
 * Shared by the home hero and the `/genes` browse page so both surfaces present
 * exactly one search affordance with identical behaviour: submitting navigates
 * to the global search route with `q`, which keeps the result view shareable and
 * URL-addressable (`public-web-layout` design: results are parameterised).
 *
 * antd's `Input` does not forward `data-testid` to the DOM, so the handle lives
 * on the wrapper and the field is labelled through `aria-label`.
 */
import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { SearchOutlined } from "@ant-design/icons";
import { Button, Input } from "@/lib/antd";

export interface PortalSearchBoxProps {
  /** Vertical scale; the hero and the browse page differ only in emphasis. */
  size?: "large" | "middle";
  /** Test handle for the wrapper element. */
  testId?: string;
  /** Seed value, e.g. an existing `?q=` when re-rendering a results route. */
  defaultValue?: string;
}

export function PortalSearchBox({
  size = "large",
  testId = "portal-search-box",
  defaultValue = "",
}: PortalSearchBoxProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [term, setTerm] = React.useState(defaultValue);
  const placeholder = t("home.searchPlaceholder", {
    defaultValue: "搜索基因 ID、变异或突变系公开编号…",
  });

  const submit = () => {
    const q = term.trim();
    void navigate({ to: "/search", search: { q: q || undefined } });
  };

  return (
    <div
      role="search"
      data-testid={testId}
      className="mx-auto flex w-full max-w-2xl flex-wrap items-center justify-center gap-2.5"
    >
      <Input
        size={size}
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        onPressEnter={submit}
        placeholder={placeholder}
        prefix={<SearchOutlined style={{ color: "var(--muted-foreground)" }} />}
        style={{ flex: 1, minWidth: 220 }}
        aria-label={placeholder}
      />
      <Button type="primary" size={size} onClick={submit} data-testid={`${testId}-submit`}>
        {t("home.searchButton", { defaultValue: "搜索" })}
      </Button>
    </div>
  );
}

export default PortalSearchBox;
