import { WorkspaceDrawer } from "../WorkspaceDrawer";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";

export function WorkspaceRuntimeDraftConflictDrawer({ workspaceDraft }: {
  workspaceDraft: WorkspaceDraftController;
}) {
  const conflict = workspaceDraft.runtimeDraftConflict;
  if (!conflict) return null;

  return <WorkspaceDrawer
    title="Draft 内容冲突"
    description="另一个标签页已为此内容创建 Draft。本地缓冲仍保留且尚未保存；请载入已保存版本，或检查三份内容后手动合并。"
    wide
    closeable={false}
    onClose={() => undefined}
  >
    {workspaceDraft.error && <p className="editor-notice error-notice" role="alert">{workspaceDraft.error}</p>}
    <div className="conflict-columns">
      <ConflictColumn title="当前正式版" content={conflict.canonicalContent} />
      <ConflictColumn title="另一个标签页已保存的 Draft" content={conflict.existingDraft.content} />
      <ConflictColumn title="本地未保存缓冲" content={conflict.localContent} />
    </div>
    <label className="field-label merge-label">
      手动合并内容
      <span>编辑后将以 Draft revision {conflict.existingDraft.revision} 为预期版本保存；若版本已变化，系统会保留冲突并重新载入最新版本。</span>
      <textarea
        className="merge-textarea"
        value={workspaceDraft.runtimeMergeContent}
        onChange={(event) => workspaceDraft.setRuntimeMergeContent(event.target.value)}
        spellCheck={false}
      />
    </label>
    <div className="editor-main-actions drawer-footer">
      <button className="button button-secondary" type="button" onClick={() => void workspaceDraft.reloadExistingDraft()}>
        载入已保存 Draft
      </button>
      <button className="button button-primary" type="button" onClick={() => void workspaceDraft.applyRuntimeMerge().catch(() => undefined)}>
        保存手动合并
      </button>
    </div>
  </WorkspaceDrawer>;
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}
