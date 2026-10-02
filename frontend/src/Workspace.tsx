import { useState } from "react";
import { WorkspaceEditingSurface } from "./WorkspaceEditing";
import { EntityPage } from "./Pages";
import { WorkspaceShell } from "./workspace/WorkspaceShell";
import type { EntityType } from "./api";
import { entityWorkspaceUrl } from "./workspaceRoute.js";

type WorkspaceMode = "read" | "edit";

export function WorkspacePage({
  type,
  id,
  navigate,
  collectionId,
  batchCollectionId,
  initialMode = "read",
}: {
  type: EntityType;
  id: string;
  navigate: (path: string) => void;
  collectionId?: string;
  batchCollectionId?: string;
  initialMode?: WorkspaceMode;
}) {
  const [mode, setMode] = useState<WorkspaceMode>(initialMode);

  function navigateFromEditor(path: string) {
    const currentEntityPath = entityWorkspaceUrl(type, id).split("?")[0];
    const target = new URL(path, window.location.origin);
    if (target.pathname === currentEntityPath) {
      const currentQuery = new URLSearchParams(window.location.search);
      if (currentQuery.has("edit") || currentQuery.has("publishAll") || target.search !== window.location.search) {
        navigate(path);
      } else {
        setMode("read");
      }
      return;
    }
    navigate(path);
  }

  return <WorkspaceShell type={type} id={id}>
    {mode === "edit"
      ? <WorkspaceEditingSurface key={`edit:${type}:${id}`} type={type} id={id} navigate={navigateFromEditor} batchCollectionId={batchCollectionId} returnCollectionId={collectionId ?? batchCollectionId} />
      : <EntityPage
        key={`read:${type}:${id}:${collectionId ?? ""}`}
        type={type}
        id={id}
        navigate={navigate}
        collectionId={collectionId}
        onEdit={() => setMode("edit")}
      />}
  </WorkspaceShell>;
}
