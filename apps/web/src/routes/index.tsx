import { createFileRoute } from "@tanstack/react-router";
import { AntdHome } from "../components/home/antd-home";
import { PageDefinitionRenderer } from "../components/page-builder/page-definition-renderer";
import { usePublishedPageDefinition } from "../lib/page-definitions";

function HomeRouteComponent() {
  const definition = usePublishedPageDefinition("/");
  if (definition.data) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-6">
        <PageDefinitionRenderer definition={definition.data} />
      </div>
    );
  }
  return <AntdHome />;
}

export const Route = createFileRoute("/")({
  component: HomeRouteComponent,
});