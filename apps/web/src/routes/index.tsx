/**
 * Public home page — driven by the published PageDefinition for "/" (Phase 8).
 *
 * The content (navigation → tool entries → news list → rich text) comes from
 * the real `/page-definitions/{route}` API via `usePageDefinition`, hydrated
 * from the SSG bootstrap when the pinned version matches. Demo/development builds
 * may use the explicit immutable seed when the API is unavailable; production
 * fails closed. The page shell retains the approved Hero search experience;
 * `resource_cards` is the CMS-managed resource-guide band selected below.
 *
 * Motion and reduced-motion behavior are preserved by the home shell.
 */
import { createFileRoute } from "@tanstack/react-router";
import { AntdHome } from "../components/home/antd-home";
import { usePageDefinition } from "../page-builder/loader";
import type { PageComponentNode } from "@soymutdb/shared";

function findResourceCards(node: PageComponentNode): PageComponentNode | undefined {
  if (node.type === "resource_cards") return node;
  for (const child of node.children ?? []) {
    const match = findResourceCards(child);
    if (match) return match;
  }
  return undefined;
}

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  const { definition } = usePageDefinition("/");
  return <AntdHome resourceCards={definition ? findResourceCards(definition.root) : undefined} />;
}
