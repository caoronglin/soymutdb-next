import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CommandPalette } from "./command-palette";
const navigate = vi.hoisted(() => vi.fn());
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => navigate }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(cleanup);
it("opens the genome browser tool rather than an assembly-less viewer", () => {
  render(<CommandPalette />);
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  fireEvent.click(screen.getByRole("button", { name: /Open Genome Browser/ }));
  expect(navigate).toHaveBeenCalledWith({ to: "/search/gbrowse" });
});
