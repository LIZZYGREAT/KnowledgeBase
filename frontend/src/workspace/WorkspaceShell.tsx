import type { ReactNode } from "react";
import type { EntityType } from "../api";

const entityLabels: Record<EntityType, string> = {
  document: "文档",
  term: "术语",
  source: "来源",
};

export function WorkspaceShell({
  type,
  id,
  children,
}: {
  type: EntityType;
  id: string;
  children: ReactNode;
}) {
  return <section className="workspace-shell" aria-label={`${entityLabels[type]}工作区`} data-entity-id={id}>
    <main className="workspace-document-pane">{children}</main>
  </section>;
}
