/**
 * Public home page — driven by the published PageDefinition for "/" (Phase 8).
 *
 * The content (navigation → tool entries → news list → rich text) comes from
 * the real `/page-definitions/{route}` API via `usePageDefinition`, hydrated
 * from the SSG bootstrap when the pinned version matches, and falls back to
 * the immutable seed when the API is unavailable. The hero search and
 * statistics strip are removed (outside the approved reference structure);
 * their underlying APIs remain unchanged.
 *
 * Motion (FadeUp) and reduced-motion behavior are preserved via the
 * app-level animation policy (AnimationProvider).
 */
import { createFileRoute } from "@tanstack/react-router";
import { AntdHome } from "../components/home/antd-home";

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  return <AntdHome />;
}
