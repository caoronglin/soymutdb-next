import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReleaseReadiness } from "./release-readiness";

describe("ReleaseReadiness", () => {
  it("shows validation, responsive, plugin, and draft gates", () => {
    const onResponsiveReviewedChange = vi.fn();
    render(<ReleaseReadiness schema="invalid" responsiveReviewed={false} unsavedChanges pluginWarning="BLAST plugin is disabled" onResponsiveReviewedChange={onResponsiveReviewedChange} />);
    expect(screen.getByText(/latest preview validation failed/i)).toBeInTheDocument();
    expect(screen.getByText(/BLAST plugin is disabled/i)).toBeInTheDocument();
    expect(screen.getByText(/save current changes/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed desktop/i }));
    expect(onResponsiveReviewedChange).toHaveBeenCalledWith(true);
  });

  it("reports a fully reviewed, valid saved draft", () => {
    render(<ReleaseReadiness schema="valid" responsiveReviewed unsavedChanges={false} onResponsiveReviewedChange={vi.fn()} />);
    expect(screen.getByText(/latest preview validation passed/i)).toBeInTheDocument();
    expect(screen.getByText(/no unsaved local changes/i)).toBeInTheDocument();
  });

  it("renders authoritative launcher capability checks", () => {
    render(<ReleaseReadiness schema="valid" responsiveReviewed unsavedChanges={false} pluginStatuses={[{ key: "blast", available: false, reason: "plugin_disabled" }, { key: "jbrowse", available: true, reason: null }]} onResponsiveReviewedChange={vi.fn()} />);
    expect(screen.getByText(/Plugin blast/i)).toBeInTheDocument();
    expect(screen.getByText("plugin_disabled")).toBeInTheDocument();
    expect(screen.getByText(/Plugin jbrowse/i)).toBeInTheDocument();
    expect(screen.getByText(/authoritative capability check passed/i)).toBeInTheDocument();
  });
});
