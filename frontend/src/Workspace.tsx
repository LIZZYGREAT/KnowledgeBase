import { useState } from "react";
import { EditorPage } from "./Editor";
import { EntityPage } from "./Pages";
import type { EntityType } from "./api";

type WorkspaceMode = "read" | "edit";

export function WorkspacePage({
  type,
  id,
  navigate,
  collectionId,
  initialMode = "read",
}: {
  type: EntityType;
  id: string;
  navigate: (path: string) => void;
  collectionId?: string;
  initialMode?: WorkspaceMode;
}) {
  const [mode, setMode] = useState<WorkspaceMode>(initialMode);
  const entityPath = `/${type === "document" ? "documents" : `${type}s`}/${encodeURIComponent(id)}`;

  function navigateFromEditor(path: string) {
    if (path === entityPath || path === "/library" || path === "/terms") {
      setMode("read");
      return;
    }
    navigate(path);
  }

  if (mode === "edit") {
    return <EditorPage key={`edit:${type}:${id}`} type={type} id={id} navigate={navigateFromEditor} />;
  }
  return <EntityPage
    key={`read:${type}:${id}:${collectionId ?? ""}`}
    type={type}
    id={id}
    navigate={navigate}
    collectionId={collectionId}
    onEdit={() => setMode("edit")}
  />;
}
