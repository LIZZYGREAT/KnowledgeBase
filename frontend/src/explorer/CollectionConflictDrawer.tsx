import type { DraftComparison } from "../api";
import { WorkspaceDrawer } from "../WorkspaceDrawer";

export function CollectionConflictDrawer({
  comparison,
  mergeContent,
  busy,
  onMergeContentChange,
  onReloadCanonical,
  onApplyRebase,
  onClose,
}: {
  comparison: DraftComparison;
  mergeContent: string;
  busy: boolean;
  onMergeContentChange: (content: string) => void;
  onReloadCanonical: () => void;
  onApplyRebase: () => void;
  onClose: () => void;
}) {
  return <WorkspaceDrawer
    title="解决专题冲突"
    description="比较未发布修改的基线、当前正式版本和未发布修改内容。重新载入会删除未发布修改；保留并重设基线会继续保留未发布修改，均不会发布。"
    wide
    onClose={onClose}
  >
    <div className="conflict-columns">
      <ConflictColumn title="基线专题" content={comparison.base_content} />
      <ConflictColumn title="当前正式版本专题" content={comparison.current_content} />
      <ConflictColumn title="已保存的未发布修改" content={comparison.draft.content} />
    </div>
    <label className="field-label merge-label">手动合并 YAML
      <span>编辑完整专题 YAML；保存后会将未发布修改基线更新为当前正式版本。</span>
      <textarea
        className="merge-textarea"
        value={mergeContent}
        onChange={(event) => onMergeContentChange(event.target.value)}
        spellCheck={false}
        aria-label="手动合并专题 YAML"
      />
    </label>
    <div className="editor-main-actions drawer-footer">
      <button className="button button-secondary" disabled={busy} onClick={onReloadCanonical}>放弃未发布修改并载入正式版本</button>
      <button className="button button-primary" disabled={busy || !mergeContent.trim()} onClick={onApplyRebase}>保留未发布修改并重设基线</button>
    </div>
  </WorkspaceDrawer>;
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}
