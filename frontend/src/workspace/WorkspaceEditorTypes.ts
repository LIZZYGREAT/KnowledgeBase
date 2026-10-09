import type { EntityType } from "../api";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";

export interface WorkspaceEditorContext {
  type: EntityType;
  id: string;
  navigate: (path: string) => void;
  workspaceDraft: WorkspaceDraftController;
  batchCollectionId?: string;
  additionalDraftIds?: string[];
  researchGroupId?: string;
  returnCollectionId?: string;
  proposalGeneratedOnLoad?: boolean;
}
