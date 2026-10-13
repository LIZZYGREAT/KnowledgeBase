import { useEffect, useState } from "react";
import { errorMessage } from "../errors";
import { listAllEntities, type Collection as CollectionData, type Draft, type EntitySummary } from "../api";
import { Chip, EmptyState, ErrorState, LoadingState } from "../ui";
import type { DraftCollection } from "../collectionDraftModel";
import type { CollectionDraftStatus } from "../useCollectionDraft";
export function CollectionDraftToolbar({
  collection,
  status,
  draft,
  organizationOrderDraft,
  error,
  notice,
  editMode,
  busy,
  onToggleEdit,
  onEditMetadata,
  onAddExisting,
  onNewSection,
  onArchive,
  onPublish,
  onDiscard,
  onReviewConflict,
}: {
  collection: CollectionData | DraftCollection | null;
  status: CollectionDraftStatus;
  draft: Draft | null;
  organizationOrderDraft: boolean;
  error: string;
  notice: string;
  editMode: boolean;
  busy: boolean;
  onToggleEdit: () => void;
  onEditMetadata: () => void;
  onAddExisting: () => void;
  onNewSection: () => void;
  onArchive: () => void;
  onPublish: () => void;
  onDiscard: () => void;
  onReviewConflict: () => void;
}) {
  if (!collection) return null;
  const archived = collection.status === "archived";
  const isConflict = status === "runtime-conflict" || status === "canonical-conflict";
  const discardBlocked = status === "saving" || isConflict;
  const canEdit = editMode && !archived && !organizationOrderDraft && !busy && status !== "loading" && status !== "error" && !isConflict;
  const statusLabel = organizationOrderDraft ? "已自动保存排序修改，等待确认"
    : status === "loading" ? "正在读取修改…"
    : status === "error" ? "修改需要处理"
    : status === "unsaved" ? "Unsaved changes"
      : status === "saving" ? "正在保存修改…"
        : status === "saved" ? "修改已自动保存，尚未正式收录"
          : isConflict ? "修改需要处理"
            : "正式版本";
  const hasChanges = organizationOrderDraft || Boolean(draft) || status === "unsaved" || status === "saving" || isConflict;
  return <section className="explorer-edit-toolbar surface" aria-label="专题 editing">
    <div className="explorer-edit-toolbar-main">
      <Chip tone={isConflict ? "orange" : hasChanges ? "blue" : "neutral"}>{statusLabel}</Chip>
      <div className="explorer-edit-toolbar-actions">
        <button className="button button-secondary" onClick={onEditMetadata} disabled={busy || organizationOrderDraft || status === "loading" || status === "error" || isConflict}>编辑名称与描述</button>
        {archived
          ? <button className="button button-secondary" onClick={onArchive} disabled={busy || organizationOrderDraft || status === "loading" || status === "error"}>恢复专题</button>
          : <>
            <button className={`button ${editMode ? "button-secondary" : "button-primary"}`} onClick={onToggleEdit} disabled={organizationOrderDraft || status === "loading" || status === "error" || isConflict || busy}>{editMode ? "完成编辑" : "编辑结构"}</button>
            <button className="button button-secondary" onClick={onAddExisting} disabled={!canEdit}>加入已有内容</button>
            <button className="button button-secondary" onClick={onNewSection} disabled={!canEdit}>新建分组</button>
            <button className="button button-quiet" onClick={onArchive} disabled={organizationOrderDraft || busy || status === "loading" || status === "error" || isConflict}>归档</button>
          </>}
        {isConflict && <button className="button button-secondary" onClick={onReviewConflict} disabled={busy}>处理版本冲突</button>}
        {organizationOrderDraft && <span className="explorer-action-notice">请使用侧栏的保存排序更改统一发布排序。</span>}
        {hasChanges && !organizationOrderDraft && <>
          <button className="button button-secondary" onClick={onDiscard} disabled={busy || status === "loading" || discardBlocked} title={discardBlocked ? "请等待保存完成或先处理冲突" : undefined}>丢弃修改</button>
          {discardBlocked && <span className="subtle-copy" role="status">请等待保存完成或先处理冲突</span>}
          <button className="button button-primary" onClick={onPublish} disabled={busy || status === "loading" || isConflict || status === "error"}>确认保存</button>
        </>}
      </div>
    </div>
    {error && <p className="error-copy" role="alert">{error}</p>}
    {notice && <p className="explorer-action-notice" role="status">{notice}</p>}
  </section>;
}

export function AddExistingEntityDialog({
  parentSectionId,
  onClose,
  onChoose,
}: {
  parentSectionId: string | null;
  onClose: () => void;
  onChoose: (entity: EntitySummary) => void;
}) {
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([listAllEntities("document"), listAllEntities("term"), listAllEntities("source")])
      .then((groups) => { if (active) setEntities(groups.flat()); })
      .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = entities.filter((item) => !normalized || `${item.title} ${item.id} ${item.entity_type}`.toLocaleLowerCase().includes(normalized));
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="add-existing-title">
      <div className="section-heading"><div><h2 id="add-existing-title">加入已有内容</h2><p>{parentSectionId ? "添加到所选分组" : "添加到专题根目录"}</p></div><button className="text-button" onClick={onClose}>关闭</button></div>
      <label className="field-label">搜索笔记、术语或文献<input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="标题、ID 或类型" /></label>
      <div className="explorer-add-results" aria-live="polite">
        {loading ? <LoadingState label="正在读取知识条目…" /> : error ? <ErrorState message={error} /> : filtered.length ? filtered.map((entity) => <button key={`${entity.entity_type}:${entity.id}`} onClick={() => onChoose(entity)}>
          <span><strong>{entity.title}</strong><small>{entity.id}</small></span><Chip>{entity.entity_type}</Chip>
        </button>) : <EmptyState title="没有匹配的 Entity" description="尝试其他标题、ID 或类型。" />}
      </div>
    </section>
  </div>;
}

export function CreateCollectionDialog({
  error,
  busy,
  onClose,
  onCreate,
}: {
  error: string;
  busy: boolean;
  onClose: () => void;
  onCreate: (id: string, title: string, description: string) => void;
}) {
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="create-collection-title">
      <div className="section-heading"><div><h2 id="create-collection-title">新建专题</h2><p>把相关笔记、术语和文献组织在一起。创建后可添加分组和内容引用。</p></div><button className="text-button" onClick={onClose} disabled={busy}>关闭</button></div>
      <form className="explorer-create-form" onSubmit={(event) => { event.preventDefault(); onCreate(id, title, description); }}>
        <label className="field-label">专题标识<input autoFocus required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={id} onChange={(event) => setId(event.target.value)} placeholder="continual-learning" /></label>
        <p className="field-hint">专题标识用于稳定链接：使用小写英文、数字和连字符，例如 continual-learning。</p>
        <label className="field-label">名称<input required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="持续学习" /></label>
        <label className="field-label">描述（可选）<textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这条知识路径的目标" /></label>
        {error && <p className="error-copy" role="alert">{error}</p>}
        <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? "正在发布…" : "创建专题"}</button></div>
      </form>
    </section>
  </div>;
}

export function EditCollectionMetadataDialog({
  collection,
  busy,
  onClose,
  onSave,
}: {
  collection: DraftCollection;
  busy: boolean;
  onClose: () => void;
  onSave: (title: string, description: string) => void;
}) {
  const [title, setTitle] = useState(collection.title);
  const [description, setDescription] = useState(collection.description ?? "");
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="edit-collection-title">
      <div className="section-heading"><div><h2 id="edit-collection-title">编辑专题详情</h2><p>名称和描述先保存到运行时未发布修改，发布后更新正式版本。</p></div><button className="text-button" onClick={onClose} disabled={busy}>关闭</button></div>
      <form className="explorer-create-form" onSubmit={(event) => { event.preventDefault(); onSave(title, description); }}>
        <label className="field-label">名称<input autoFocus required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="field-label">描述（可选）<textarea rows={4} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button-primary" type="submit" disabled={busy || !title.trim()}>保存到未发布修改</button></div>
      </form>
    </section>
  </div>;
}

export function NewNoteHereDialog({
  sectionTitle,
  error,
  busy,
  createdDraft,
  onClose,
  onCreate,
  onContinue,
}: {
  sectionTitle: string;
  error: string;
  busy: boolean;
  createdDraft: Draft | null;
  onClose: () => void;
  onCreate: (title: string, documentType: "paper-note" | "learning-note" | "course-note") => void;
  onContinue: () => void;
}) {
  const [title, setTitle] = useState("");
  const [documentType, setDocumentType] = useState<"paper-note" | "learning-note" | "course-note">("learning-note");
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="new-note-here-title">
      <div className="section-heading"><div><h2 id="new-note-here-title">在此新建笔记</h2><p>将在 “{sectionTitle}” 下创建笔记，并与待确认的专题修改一起发布。</p></div><button className="text-button" onClick={onClose} disabled={busy}>关闭</button></div>
      <form className="explorer-create-form" onSubmit={(event) => { event.preventDefault(); onCreate(title.trim(), documentType); }}>
        <label className="field-label">笔记标题<input autoFocus required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：Transformer 阅读笔记" disabled={Boolean(createdDraft)} /></label>
        <label className="field-label">笔记类型<select value={documentType} onChange={(event) => setDocumentType(event.target.value as typeof documentType)} disabled={Boolean(createdDraft)}><option value="learning-note">学习笔记</option><option value="paper-note">论文笔记</option><option value="course-note">课程笔记</option></select></label>
        {createdDraft && <p className="trust-note">笔记未发布修改 {createdDraft.entity_id} 已创建。保存分组的待确认的专题修改后可继续编辑。</p>}
        {error && <p className="error-copy" role="alert">{error}</p>}
        <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button>{createdDraft
          ? <button className="button button-primary" type="button" disabled={busy} onClick={onContinue}>{busy ? "正在保存目录…" : "重试并进入编辑"}</button>
          : <button className="button button-primary" type="submit" disabled={busy || !title.trim()}>{busy ? "正在创建未发布修改…" : "创建未发布修改并编辑"}</button>}</div>
      </form>
    </section>
  </div>;
}
