import { WorkspaceDrawer } from "../WorkspaceDrawer";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";

export function WorkspaceConflictDrawer({ comparison, content, mergeContent, onMergeContentChange, onReloadCanonical, onApplyRebase, onClose }: {
  comparison: NonNullable<WorkspaceDraftController["comparison"]>;
  content: string;
  mergeContent: string;
  onMergeContentChange: (value: string) => void;
  onReloadCanonical: () => void;
  onApplyRebase: () => void;
  onClose: () => void;
}) {
  return <WorkspaceDrawer title={comparison.canonical_changed ? "解决版本冲突" : "版本比较"} description={comparison.canonical_changed ? "请对比基线、当前正式版和 Draft，再选择重新载入或手动合并。此操作不会自动发布。" : "当前正式版与 Draft 基线一致；可以检查内容，也可以关闭此面板继续编辑。"} wide onClose={onClose}>
    <div className="conflict-columns">
      <ConflictColumn title="基线" content={comparison.base_content} />
      <ConflictColumn title="当前正式版" content={comparison.current_content} />
      <ConflictColumn title="Draft" content={content} />
    </div>
    <label className="field-label merge-label">合并内容 <span>初始为当前 Draft；请参考上方版本对比，手动合入需要保留的修改。</span>
      <textarea className="merge-textarea" value={mergeContent} onChange={(event) => onMergeContentChange(event.target.value)} spellCheck={false} />
    </label>
    <div className="editor-main-actions drawer-footer"><button className="button button-secondary" onClick={onReloadCanonical}>放弃 Draft 并载入当前正式版</button><button className="button button-primary" onClick={onApplyRebase}>保留 Draft 并重设基线</button></div>
  </WorkspaceDrawer>;
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}
