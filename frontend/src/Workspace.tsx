import { lazy, Suspense, useEffect } from "react";
import { EntityPage } from "./Pages";
import { WorkspaceShell } from "./workspace/WorkspaceShell";
import { useWorkspaceDraft } from "./useWorkspaceDraft";
import { WorkspaceRuntimeDraftConflictDrawer } from "./workspace/WorkspaceRuntimeDraftConflictDrawer";
import type { EntityType } from "./api";
import { entityWorkspaceUrl } from "./workspaceRoute";
import { useWorkspaceEditorController } from "./workspace/useWorkspaceEditorController";
import { errorMessage } from "./errors";
import type { RegisterBeforeNavigate } from "./navigation";

const WorkspaceExplorer = lazy(() => import("./Explorer").then((module) => ({ default: module.ExplorerPage })));

export function WorkspacePage({
  type,
  id,
  navigate,
  registerBeforeNavigate,
  collectionId,
  batchCollectionId,
}: {
  type: EntityType;
  id: string;
  navigate: (path: string) => void;
  registerBeforeNavigate?: RegisterBeforeNavigate;
  collectionId?: string;
  batchCollectionId?: string;
}) {
  const workspaceDraft = useWorkspaceDraft(type, id);
  useEffect(() => {
    if (!registerBeforeNavigate) return;
    return registerBeforeNavigate(async () => {
      if (!workspaceDraft.isDirty) return true;
      try {
        await workspaceDraft.saveNow();
        return true;
      } catch (reason) {
        workspaceDraft.setError(errorMessage(reason));
        return false;
      }
    });
  }, [registerBeforeNavigate, workspaceDraft.isDirty, workspaceDraft.saveNow, workspaceDraft.setError]);
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
            key={`explorer:${collectionId ?? ""}:${batchCollectionId ? "batch" : "normal"}`}
            embedded
            readOnly={Boolean(batchCollectionId)}
            selectedEntity={{ type, id }}
            onOpen={(entityType, entityId) => navigate(entityWorkspaceUrl(entityType, entityId))}
            navigate={navigate}
            registerBeforeNavigate={registerBeforeNavigate}
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
