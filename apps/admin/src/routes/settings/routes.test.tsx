import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SettingsOverviewPage from "./index";
import { SettingsDomainPage } from "./section-page";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...props}>{children}</a>
  ),
}));

vi.mock("../settings", () => ({
  default: ({ domain }: { domain?: string }) => <div data-testid="settings-form">{domain ?? "legacy"}</div>,
}));

vi.mock("./site-form", () => ({
  SiteSettingsForm: () => <div data-testid="site-settings-form">site editor</div>,
}));

vi.mock("./localization-form", () => ({
  LocalizationSettingsForm: () => <div data-testid="localization-settings-form">localization editor</div>,
}));

vi.mock("./security-form", () => ({
  SecuritySettingsForm: () => <div data-testid="security-settings-form">security editor</div>,
}));

vi.mock("./revision-history", () => ({
  SettingsRevisionHistory: ({ sections }: { sections: Array<{ id: string }> }) => <div data-testid="revision-history">{sections[0]?.id}</div>,
}));

describe("settings domain routes", () => {
  it("renders every domain as a discoverable overview link", () => {
    render(<SettingsOverviewPage />);
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Site information/ })).toHaveAttribute("href", "/settings/site");
    expect(screen.getByRole("link", { name: /Security/ })).toHaveAttribute("href", "/settings/security");
    expect(screen.getByRole("link", { name: "Open the complete settings form" })).toHaveAttribute("href", "/settings/legacy");
  });

  it("renders the local site form without mounting the legacy form", () => {
    render(<SettingsDomainPage domain="site" />);
    expect(screen.getByTestId("site-settings-form")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-form")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "complete settings form" })).toHaveAttribute("href", "/settings/legacy");
  });

  it("renders the local localization form without mounting the legacy form", () => {
    render(<SettingsDomainPage domain="localization" />);
    expect(screen.getByTestId("localization-settings-form")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-form")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "complete settings form" })).toHaveAttribute("href", "/settings/legacy");
  });

  it("renders the local security form without mounting the legacy form", () => {
    render(<SettingsDomainPage domain="security" />);
    expect(screen.getByTestId("security-settings-form")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-form")).not.toBeInTheDocument();
    expect(screen.getByTestId("revision-history")).toHaveTextContent("security");
  });

  it("renders a focused domain and passes its domain to the legacy form", () => {
    render(<SettingsDomainPage domain="integrations" />);
    expect(screen.getByRole("heading", { name: "Integrations" })).toBeInTheDocument();
    expect(screen.getByTestId("settings-form")).toHaveTextContent("integrations");
    expect(screen.getByTestId("revision-history")).toHaveTextContent("cdn");
    expect(screen.getByRole("link", { name: "Settings overview" })).toHaveAttribute("href", "/settings");
  });
});
