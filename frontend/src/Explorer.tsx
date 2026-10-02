import type { CSSProperties } from "react";
import { addEntityReference, moveCollectionSibling, removeCollectionNode } from "./collectionEditing.js";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "./ui";
import { CollectionConflictDrawer } from "./explorer/CollectionConflictDrawer";
import { AddExistingEntityDialog, CollectionDraftToolbar, CreateCollectionDialog, EditCollectionMetadataDialog, NewNoteHereDialog } from "./explorer/ExplorerDialogs";
import { CollectionOverview, VirtualViewButton, VirtualViewContent } from "./explorer/ExplorerViews";
import { CollectionTree } from "./explorer/ExplorerTree";
import type { ExplorerPageProps } from "./explorer/ExplorerTypes";
import { useExplorerController } from "./explorer/useExplorerController";
import { PublishOutcomeNotice } from "./workspace/PublishOutcomeNotice";
import { WorkspacePublishDrawer } from "./workspace/WorkspacePublishDrawer";

export function ExplorerPage(props: ExplorerPageProps) {
  const {
    onOpen, navigate, embedded, selectedEntity, selectedCollectionId, setSelectedCollectionId,
    expandedSections, panelWidth, setPanelWidth, view, setView, treeFilter, setTreeFilter, editMode, setEditMode,
    addDialogParent, addDialogOpen, setAddDialogOpen, createCollectionOpen, setCreateCollectionOpen,
    editCollectionMetadataOpen, setEditCollectionMetadataOpen, createCollectionError, setCreateCollectionError,
    newNoteTarget, newNoteError, setNewNoteError, newNoteBusy, createdNoteDraft,
    copyingEntity, setCopyingEntity, copyTargetId, setCopyTargetId, actionError, setActionError,
    actionNotice, publishOutcome, collectionPublishReview, setCollectionPublishReview,
    collectionReviewBusy, collectionPublishing, collectionConflictOpen, setCollectionConflictOpen, busy,
    collectionsResource, collections, collectionResource, virtualResource, collection, collectionDraft,
    displayedCollection, treeEditMode, filteredNodes, changeDraft, openAddExisting, addExistingEntity,
    createSection, renameSection, deleteSection, handleDrop, startNodeDrag, startReferenceDrag,
    updateProgress, copyEntityToCollection, startNewNoteHere, createNoteHere, enterNewNoteWorkspace,
    cancelNewNoteHere, toggleArchive, saveCollectionMetadata, moveSelectedCollection,
    reviewCollectionDraftPublish, publishCollectionDraft, createCollection, discardCollectionDraft, reloadCanonicalCollection,
    keepDraftAndRebaseCollection, reviewCollectionConflict, toggleSection, openCollectionEntity,
    startResize, moveResize, stopResize, containsEntityReference, errorMessage,
  } = useExplorerController(props);
  const layoutStyle = { "--explorer-width": `${panelWidth}px` } as CSSProperties;  return (
    <div className={embedded ? "explorer-embedded" : "page-stack"}>
      {!embedded && <PageHeader
        eyebrow="BROWSE CANONICAL KNOWLEDGE"
        title="Knowledge Explorer"
        description="按 Collection 阅读有序知识路径，也可以查看全部、未归档和最近打开的笔记。"
      />}
      <div className={`explorer-layout ${embedded ? "explorer-layout-embedded" : ""}`} style={layoutStyle}>
        <aside className="explorer-sidebar surface" aria-label="Knowledge Explorer navigation">
          <div className="explorer-sidebar-header">
            <span className="eyebrow">COLLECTION</span>
            <div className="explorer-sidebar-header-actions">
              {collectionsResource.error ? <button className="text-button" onClick={collectionsResource.retry}>重试</button> : null}
              <button className="text-button" onClick={() => { setCreateCollectionError(""); setCreateCollectionOpen(true); }}>New Collection</button>
            </div>
          </div>
          {collectionsResource.loading ? <LoadingState label="正在读取 Collections…" /> : collectionsResource.error ? (
            <ErrorState message={collectionsResource.error} retry={collectionsResource.retry} />
          ) : <label className="explorer-select-label">
            <span className="visually-hidden">选择 Collection</span>
            <select
              aria-label="选择 Collection"
              value={selectedCollectionId}
              onChange={(event) => {
                const nextCollectionId = event.target.value;
                void collectionDraft.flush()
                  .then(() => {
                    setSelectedCollectionId(nextCollectionId);
                    if (embedded) {
                      const search = new URLSearchParams(window.location.search);
                      if (nextCollectionId) search.set("collection", nextCollectionId);
                      else search.delete("collection");
                      navigate(`${window.location.pathname}${search.size ? `?${search}` : ""}${window.location.hash}`);
                    }
                  })
                  .catch((reason: unknown) => setActionError(errorMessage(reason)));
                setView("collection");
              }}
            >
              <option value="">选择 Collection</option>
              {collections.map((item) => <option key={item.id} value={item.id}>{item.title}{item.status === "archived" ? " · Archived" : ""}</option>)}
            </select>
          </label>}
          {!collectionsResource.loading && !collectionsResource.error && <div className="explorer-collection-order-actions" aria-label="调整 Collection 顺序">
            <button className="button button-quiet" type="button" aria-label="上移此 Collection 并发布排序" title="上移并通过 Publisher 发布顺序" disabled={busy || !selectedCollectionId || collections.findIndex((item) => item.id === selectedCollectionId) <= 0} onClick={() => void moveSelectedCollection("up")}>↑ 上移</button>
            <button className="button button-quiet" type="button" aria-label="下移此 Collection 并发布排序" title="下移并通过 Publisher 发布顺序" disabled={busy || !selectedCollectionId || collections.findIndex((item) => item.id === selectedCollectionId) < 0 || collections.findIndex((item) => item.id === selectedCollectionId) >= collections.length - 1} onClick={() => void moveSelectedCollection("down")}>↓ 下移</button>
            {collectionDraft.collection && <button className="button button-quiet" type="button" disabled={busy || collectionDraft.status === "loading" || collectionDraft.status === "conflict"} onClick={() => setEditCollectionMetadataOpen(true)}>编辑详情</button>}
          </div>}

          <label className="explorer-filter">
            <span aria-hidden="true">⌕</span>
            <input value={treeFilter} onChange={(event) => setTreeFilter(event.target.value)} placeholder="Filter tree…" aria-label="Filter Collection tree" />
          </label>

          <div className="explorer-tree-scroll">
            {collectionResource.loading && selectedCollectionId ? <LoadingState label="正在读取目录…" /> : null}
            {collectionResource.error && selectedCollectionId ? <ErrorState message={collectionResource.error} retry={collectionResource.retry} /> : null}
            {collection && <CollectionTree
              nodes={filteredNodes}
              collectionId={displayedCollection?.id ?? collection.id}
              expandedSections={expandedSections}
              filter={treeFilter}
              onToggle={toggleSection}
              onOpen={openCollectionEntity}
              selectedEntity={selectedEntity}
              editMode={treeEditMode}
              onStartDrag={startNodeDrag}
              onDrop={handleDrop}
              onRemove={(node) => changeDraft((current) => removeCollectionNode(current, node.id))}
              onProgress={(node) => void updateProgress(node)}
              canUpdateProgress={(node) => Boolean(collection && containsEntityReference(collection.nodes, node.entity_type, node.entity_id))}
              onCopy={(node) => { setCopyingEntity(node); setCopyTargetId(""); }}
              onAddExisting={openAddExisting}
              onNewSection={createSection}
              onRenameSection={renameSection}
              onMoveSibling={(nodeId, direction) => changeDraft((current) => moveCollectionSibling(current, nodeId, direction))}
              onDeleteSection={deleteSection}
              onNewNoteHere={(sectionId, sectionTitle) => startNewNoteHere(sectionId, sectionTitle)}
            />}
            {!collectionResource.loading && !selectedCollectionId && <EmptyState title="还没有 Collection" description="发布的 Collection 会显示在这里。" />}
          </div>

          <nav className="explorer-virtual-views" aria-label="Virtual views">
            <span className="eyebrow">VIRTUAL VIEWS</span>
            <VirtualViewButton active={view === "all"} onClick={() => setView("all")} icon="▤" label="All Documents" />
            <VirtualViewButton active={view === "unfiled"} onClick={() => setView("unfiled")} icon="○" label="Unfiled" />
            <VirtualViewButton active={view === "recent"} onClick={() => setView("recent")} icon="◷" label="Recent" />
          </nav>
        </aside>

        <div
          className="explorer-resizer"
          role="separator"
          aria-label="调整 Explorer 宽度"
          aria-orientation="vertical"
          aria-valuemin={220}
          aria-valuemax={420}
          aria-valuenow={panelWidth}
          tabIndex={0}
          onPointerDown={startResize}
          onPointerMove={moveResize}
          onPointerUp={stopResize}
          onPointerCancel={stopResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setPanelWidth((width) => Math.max(220, width - 16));
            if (event.key === "ArrowRight") setPanelWidth((width) => Math.min(420, width + 16));
          }}
        />

        <main className="explorer-content surface">
          {publishOutcome && <PublishOutcomeNotice outcome={publishOutcome} />}
          {collection && <CollectionDraftToolbar
            collection={displayedCollection}
            status={collectionDraft.status}
            draft={collectionDraft.draft}
            error={collectionDraft.error || actionError}
            notice={actionNotice}
            editMode={editMode}
            busy={busy || collectionReviewBusy}
            onToggleEdit={() => setEditMode((current) => !current)}
            onEditMetadata={() => setEditCollectionMetadataOpen(true)}
            onAddExisting={() => openAddExisting()}
            onNewSection={() => createSection()}
            onArchive={() => void toggleArchive()}
            onPublish={() => void reviewCollectionDraftPublish()}
            onDiscard={() => void discardCollectionDraft()}
            onReviewConflict={() => void reviewCollectionConflict()}
          />}
          {view === "collection" ? <>
            <CollectionOverview
            collection={displayedCollection}
            loading={collectionResource.loading}
            error={collectionResource.error || collectionDraft.error}
            retry={collectionResource.retry}
            onToggle={toggleSection}
            onOpen={openCollectionEntity}
          />
          </> : <VirtualViewContent
            view={view}
            resource={virtualResource}
            onOpen={(type, id) => onOpen(type, id)}
            editMode={treeEditMode}
            onStartDrag={startReferenceDrag}
            onAdd={(entity) => changeDraft((current) => addEntityReference(current, entity.entity_type, entity.id, entity.title))}
          />}
        </main>
      </div>
      {addDialogOpen && <AddExistingEntityDialog
        parentSectionId={addDialogParent}
        onClose={() => setAddDialogOpen(false)}
        onChoose={addExistingEntity}
      />}
      {createCollectionOpen && <CreateCollectionDialog
        error={createCollectionError}
        busy={busy}
        onClose={() => setCreateCollectionOpen(false)}
        onCreate={(id, title, description) => void createCollection(id, title, description)}
      />}
      {editCollectionMetadataOpen && collectionDraft.collection && <EditCollectionMetadataDialog
        collection={collectionDraft.collection}
        busy={busy || collectionDraft.status === "loading" || collectionDraft.status === "conflict"}
        onClose={() => setEditCollectionMetadataOpen(false)}
        onSave={saveCollectionMetadata}
      />}
      {newNoteTarget && <NewNoteHereDialog
        sectionTitle={newNoteTarget.title}
        error={newNoteError}
        busy={newNoteBusy}
        createdDraft={createdNoteDraft}
        onClose={() => void cancelNewNoteHere()}
        onCreate={(title, type) => void createNoteHere(title, type)}
        onContinue={() => createdNoteDraft && void enterNewNoteWorkspace(createdNoteDraft).catch((reason: unknown) => setNewNoteError(errorMessage(reason)))}
      />}
      {copyingEntity && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCopyingEntity(null); }}>
        <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="copy-reference-title">
          <div className="section-heading"><div><h2 id="copy-reference-title">Copy to Collection</h2><p>{copyingEntity.title}</p></div><button className="text-button" onClick={() => setCopyingEntity(null)}>关闭</button></div>
          <label className="field-label">目标 Collection<select value={copyTargetId} onChange={(event) => setCopyTargetId(event.target.value)}>
            <option value="">选择 Active Collection</option>
            {collections.filter((item) => item.status === "active" && item.id !== displayedCollection?.id).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select></label>
          {actionError && <p className="error-copy" role="alert">{actionError}</p>}
          <div className="editor-main-actions"><button className="button button-secondary" onClick={() => setCopyingEntity(null)}>取消</button><button className="button button-primary" disabled={!copyTargetId || busy} onClick={() => void copyEntityToCollection(copyTargetId, copyingEntity)}>{busy ? "正在复制…" : "复制引用"}</button></div>
        </section>
      </div>}
      {collectionConflictOpen && collectionDraft.comparison && <CollectionConflictDrawer
        comparison={collectionDraft.comparison}
        mergeContent={collectionDraft.mergeContent}
        busy={busy}
        onMergeContentChange={collectionDraft.setMergeContent}
        onReloadCanonical={() => void reloadCanonicalCollection()}
        onApplyRebase={() => void keepDraftAndRebaseCollection()}
        onClose={() => setCollectionConflictOpen(false)}
      />}
      {collectionPublishReview && <WorkspacePublishDrawer
        items={collectionPublishReview}
        busy={collectionReviewBusy}
        publishing={collectionPublishing}
        published={false}
        error={actionError}
        batch={false}
        onClose={() => setCollectionPublishReview(null)}
        onRefresh={() => void reviewCollectionDraftPublish(true)}
        onPublish={() => void publishCollectionDraft()}
      />}
    </div>
  );
}
