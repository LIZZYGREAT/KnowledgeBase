import { lazy, Suspense } from "react";
import { EntityPage } from "./Pages";
import { WorkspaceShell } from "./workspace/WorkspaceShell";
import { useWorkspaceDraft } from "./useWorkspaceDraft";
import { WorkspaceRuntimeDraftConflictDrawer } from "./workspace/WorkspaceRuntimeDraftConflictDrawer";
import type { EntityType } from "./api";
import { entityWorkspaceUrl } from "./workspaceRoute";
import { useWorkspaceEditorController } from "./workspace/useWorkspaceEditorController";

const WorkspaceExplorer = lazy(() => import("./Explorer").then((module) => ({ default: module.ExplorerPage })));

export function WorkspacePage({
  type,
  id,
  navigate,
  collectionId,
  batchCollectionId,
}: {
  type: EntityType;
  id: string;
  navigate: (path: string) => void;
  collectionId?: string;
  batchCollectionId?: string;
}) {
  const workspaceDraft = useWorkspaceDraft(type, id);
  const workspaceEditorController = useWorkspaceEditorController({
    type,
    id,
    navigate,
    workspaceDraft,
    batchCollectionId,
    returnCollectionId: collectionId ?? batchCollectionId,
  });

  return (
    <>
      <WorkspaceShell
        type={type}
        id={id}
        explorer={<Suspense fallback={<div className="workspace-explorer-loading">正在载入 Explorer…</div>}>
          <WorkspaceExplorer
            embedded
            selectedEntity={{ type, id }}
            onOpen={(entityType, entityId) => navigate(entityWorkspaceUrl(entityType, entityId))}
            navigate={navigate}
          />
        </Suspense>}
      >
        <EntityPage
          key={`reader:${type}:${id}:${collectionId ?? ""}`}
          type={type}
          id={id}
          navigate={navigate}
          collectionId={collectionId}
          workspaceDraft={workspaceDraft}
          workspaceEditorController={workspaceEditorController}
        />
      </WorkspaceShell>
      <WorkspaceRuntimeDraftConflictDrawer workspaceDraft={workspaceDraft} />
    </>
  );
}
