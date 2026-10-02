import { WorkspaceBodyEditor } from "./workspace/WorkspaceBodyEditor";
import { ErrorState, LoadingState, PageHeader } from "./ui";
import { entityWorkspaceUrl } from "./workspaceRoute.js";
import { WorkspaceEditorDrawers } from "./workspace/WorkspaceEditorDrawers";
import type { WorkspaceEditorController } from "./workspace/useWorkspaceEditorController";
export { NewNotePage } from "./workspace/NewNotePage";

export function WorkspaceEditingSurface({ controller }: { controller: WorkspaceEditorController }) {
  const {
    type, id, navigate, batchCollectionId, returnCollectionId,
    draft, content, canonicalEntity, loading, loadError, draftError, setDraftError,
    saveState, publishedRevision, isDirty, saveError, setSaveError, setSelectedText,
    publishing, setActiveDrawer, setPublishReview, saveNow, openComparison, runPreflight,
    discardCurrentDraft, setEditorContent,
  } = controller;

  if (loading) return <LoadingState label="正在载入 Draft 编辑器…" />;
  if (loadError) return <ErrorState message={loadError} />;
  const saveStateLabel = saveState === "Ready" ? "✓ 已发布"
    : saveState === "Unsaved" ? "● 尚未发布"
      : saveState === "Saving" ? "● 正在保存…"
        : saveState === "Saved" ? draft ? "● 已保存草稿 · 尚未发布" : "✓ 已发布"
          : "● 需要解决冲突";
  const visibleSaveError = saveError || draftError;

  return (
    <div className="page-stack editor-page">
      <div className="editor-topline">
        <button className="back-link" onClick={() => navigate(canonicalEntity ? entityWorkspaceUrl(type, id, { collectionId: returnCollectionId }) : returnCollectionId ? `/explorer?collection=${encodeURIComponent(returnCollectionId)}` : "/")}>← 返回阅读</button>
        <div className="editor-save-state"><span className={`save-indicator ${saveState.toLowerCase()}`} />{saveStateLabel}</div>
      </div>
      <PageHeader
        eyebrow={`${type.toUpperCase()} · DRAFT EDITOR`}
        title={`编辑 ${id}`}
        description="区块编辑、元数据管理、AI 审阅、冲突处理与发布都在此工作区完成。"
        action={<div className="editor-main-actions workspace-tools">
          <button className="button button-secondary" onClick={() => setActiveDrawer("metadata")}>元数据</button>
          <button className="button button-secondary" disabled={type === "source"} onClick={() => setActiveDrawer("ai")}>AI 审阅</button>
          <button className="button button-secondary" disabled={!isDirty || publishing || saveState === "Conflict"} onClick={() => void saveNow().catch(() => undefined)}>保存草稿</button>
          <button className="button button-primary" disabled={publishing || saveState === "Conflict" || Boolean(publishedRevision) || (!draft && !isDirty)} onClick={() => { setPublishReview(null); setActiveDrawer("publish"); void runPreflight(); }}>{publishing ? "发布中…" : batchCollectionId ? "Publish All" : "发布"}</button>
        </div>}
      />

      <WorkspaceEditorDrawers controller={controller} />
      {visibleSaveError && <div className="editor-notice error-notice" role="alert"><span>{visibleSaveError}</span><button className="text-button" onClick={() => { setSaveError(""); setDraftError(""); }}>关闭</button>{saveState === "Conflict" && <button className="button button-secondary" onClick={() => void openComparison()}>比较版本</button>}</div>}

      <WorkspaceBodyEditor
        type={type}
        content={content}
        isDirty={isDirty}
        onChange={setEditorContent}
        onSelectionChange={setSelectedText}
        onSave={() => void saveNow().catch(() => undefined)}
        onNavigate={navigate}
      />
      <div className="editor-bottom-actions"><button className="button button-danger" disabled={!draft && !isDirty} onClick={() => void discardCurrentDraft()}>{batchCollectionId ? "丢弃笔记并撤销引用" : "丢弃 Draft"}</button><span>{batchCollectionId ? `发布目标：Document + Collection ${batchCollectionId}；丢弃笔记会保留已有 Collection 修改` : draft ? "草稿与当前正式内容关联" : "基于当前正式内容"} · Publisher 会检查外部更改</span></div>
    </div>
  );
}
