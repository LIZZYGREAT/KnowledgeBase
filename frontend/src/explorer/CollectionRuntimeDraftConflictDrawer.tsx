import type { Draft } from "../api";
import { WorkspaceDrawer } from "../WorkspaceDrawer";

export function CollectionRuntimeDraftConflictDrawer({
  conflict,
  mergeContent,
  error,
  busy,
  onMergeContentChange,
  onReloadLatest,
  onKeepLocal,
  onSaveMerge,
}: {
  conflict: { existingDraft: Draft; localContent: string; canonicalContent: string };
  mergeContent: string;
  error: string;
  busy: boolean;
  onMergeContentChange: (content: string) => void;
  onReloadLatest: () => void;
  onKeepLocal: () => void;
  onSaveMerge: () => void;
}) {
  return <WorkspaceDrawer
    title="Collection Draft 内容冲突"
    description="另一个会话更新了 Runtime Draft。当前 Canonical、最新已保存 Draft 和本地修改分别显示；解决此冲突不会发布内容。"
    wide
    closeable={false}
    onClose={() => undefined}
  >
    {error && <p className="editor-notice error-notice" role="alert">{error}</p>}
    <div className="conflict-columns">
      <ConflictColumn title="当前 Canonical Collection" content={conflict.canonicalContent} />
      <ConflictColumn title="最新 Runtime Draft" content={conflict.existingDraft.content} />
      <ConflictColumn title="本地未保存内容" content={conflict.localContent} />
    </div>
    <label className="field-label merge-label">
      手动合并 YAML
      <span>保存时会以最新 Runtime Draft revision {conflict.existingDraft.revision} 执行版本检查。</span>
      <textarea
        className="merge-textarea"
        aria-label="手动合并 Collection Draft YAML"
        value={mergeContent}
        onChange={(event) => onMergeContentChange(event.target.value)}
        spellCheck={false}
      />
    </label>
    <div className="editor-main-actions drawer-footer">
      <button className="button button-secondary" type="button" disabled={busy} onClick={onReloadLatest}>载入最新 Draft</button>
      <button className="button button-secondary" type="button" disabled={busy} onClick={onKeepLocal}>保留本地并保存</button>
      <button className="button button-primary" type="button" disabled={busy || !mergeContent.trim()} onClick={onSaveMerge}>保存手动合并</button>
    </div>
  </WorkspaceDrawer>;
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}
