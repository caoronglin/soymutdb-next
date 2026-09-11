import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportModuleMetadataStep } from "./import-module-metadata-step";

vi.mock("@/lib/antd", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
}));

function renderStep(overrides: Partial<React.ComponentProps<typeof ImportModuleMetadataStep>> = {}) {
  const props = { sourceMode: "s3" as const, releaseId: "42", moduleKey: "genes", checksum: "abc", localFileSelected: true, previewChecking: false, onReleaseIdChange: vi.fn(), onModuleKeyChange: vi.fn(), onChecksumChange: vi.fn(), onPreview: vi.fn(), ...overrides };
  render(<ImportModuleMetadataStep {...props} />);
  return props;
}

describe("ImportModuleMetadataStep", () => {
  it("forwards metadata changes and preserves the preview trigger", () => {
    const props = renderStep();
    fireEvent.change(screen.getByLabelText("Module Key"), { target: { value: "variants" } });
    fireEvent.change(screen.getByLabelText("Checksum"), { target: { value: "def" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(props.onModuleKeyChange).toHaveBeenCalledWith("variants");
    expect(props.onChecksumChange).toHaveBeenCalledWith("def");
    expect(props.onPreview).toHaveBeenCalledOnce();
  });

  it("does not expose S3 checksum for local sources and disables preview without a file", () => {
    renderStep({ sourceMode: "local", localFileSelected: false });
    expect(screen.queryByLabelText("Checksum")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  });
});
