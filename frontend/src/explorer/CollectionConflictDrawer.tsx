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
    title="解决 Collection 冲突"
    description="比较 Draft 的基线、当前 Canonical 和 Draft 内容。重新载入会删除 Draft；保留并重设基线会继续保留 Draft，均不会发布。"
    wide
    onClose={onClose}
  >
    <div className="conflict-columns">
      <ConflictColumn title="基线 Collection" content={comparison.base_content} />
      <ConflictColumn title="当前 Canonical Collection" content={comparison.current_content} />
      <ConflictColumn title="已保存的 Draft" content={comparison.draft.content} />
    </div>
    <label className="field-label merge-label">手动合并 YAML
      <span>编辑完整 Collection YAML；保存后会将 Draft 基线更新为当前 Canonical。</span>
      <textarea
        className="merge-textarea"
        value={mergeContent}
        onChange={(event) => onMergeContentChange(event.target.value)}
        spellCheck={false}
        aria-label="手动合并 Collection YAML"
      />
    </label>
    <div className="editor-main-actions drawer-footer">
      <button className="button button-secondary" disabled={busy} onClick={onReloadCanonical}>放弃 Draft 并载入 Canonical</button>
      <button className="button button-primary" disabled={busy || !mergeContent.trim()} onClick={onApplyRebase}>保留 Draft 并重设基线</button>
    </div>
  </WorkspaceDrawer>;
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}
