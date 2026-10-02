import type { EntityType } from "../api";
import type { WorkspaceSaveState } from "../useWorkspaceDraft";
import { WorkspaceDrawer } from "../WorkspaceDrawer";
import { WorkspaceBodyEditor } from "./WorkspaceBodyEditor";

export function WorkspaceSourceDrawer({
  type,
  content,
  isDirty,
  saveState,
  onChange,
  onSelectionChange,
  onNavigate,
  onSave,
  onClose,
}: {
  type: EntityType;
  content: string;
  isDirty: boolean;
  saveState: WorkspaceSaveState;
  onChange: (value: string) => void;
  onSelectionChange: (value: string) => void;
  onNavigate: (path: string) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  return <WorkspaceDrawer
    title="完整源码"
    description="高级模式可直接编辑完整 Markdown/YAML 源文；修改仍写入 Runtime Draft，发布前需检查差异。"
    wide
    onClose={onClose}
  >
    <section className="drawer-section workspace-source-drawer">
      <WorkspaceBodyEditor
        type={type}
        content={content}
        isDirty={isDirty}
        onChange={onChange}
        onSelectionChange={onSelectionChange}
        onSave={onSave}
        onNavigate={onNavigate}
      />
      <div className="drawer-footer">
        <button className="button button-secondary" type="button" onClick={onClose}>关闭</button>
        <button className="button button-primary" type="button" disabled={!isDirty || saveState === "Conflict"} onClick={onSave}>保存 Draft</button>
      </div>
    </section>
  </WorkspaceDrawer>;
}
