/**
 * Page Builder editor route for a single page definition.
 */

import { useParams } from "@tanstack/react-router";
import { PageBuilderEditor } from "../../components/page-builder/page-builder-editor";

export default function PageBuilderEditPage() {
  const { pageId } = useParams({ from: "/_auth/page-builder/$pageId" });
  return <PageBuilderEditor pageId={pageId} />;
}
