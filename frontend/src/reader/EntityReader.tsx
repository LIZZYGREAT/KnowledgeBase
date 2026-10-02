import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import {
  createPresentationAnnotation, deletePresentationAnnotation, getCollectionNavigation,
  getEntity, listPresentationAnnotations,
  type AnnotationStyleType,
  type EntityType, type PresentationAnnotation,
} from "../api";
import { ErrorState, LoadingState, titleCase } from "../ui";
import { latestIntersectingHeading } from "../readerNavigation.js";
import { splitMarkdownFrontmatter } from "../markdownBlocks.js";
import { WorkspaceInlineEditor } from "../workspace/WorkspaceInlineEditor";
import { WorkspaceSelectionToolbar } from "../workspace/WorkspaceSelectionToolbar";
import { WorkspaceSelectionAIDrawer } from "../workspace/WorkspaceSelectionAIDrawer";
import { applyMarkdownFormatting, type MarkdownFormattingAction } from "../markdownFormatting.js";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import type { WorkspaceEditorController } from "../workspace/useWorkspaceEditorController";
import { WorkspaceEditorDrawers } from "../workspace/WorkspaceEditorDrawers";
import { CollectionReaderContext, ContextCard, ContextExportPanel, MetaChipList } from "./ReaderContext";
import { maintenanceStatus, readList, readString, reviewStatus, typeLabel, entityPath, useResource, type Navigate } from "../pages/PageShared";
import { errorMessage, hashText, loadEntity, markdownHeadings, readArtifacts, recordDocumentOpenSafely, resolveReaderSelectionSourceRange, type ReaderSelection, type ReaderSourceBlock } from "./readerModel";
export function EntityPage({
  type,
  id,
  navigate,
  collectionId,
  onEdit,
  workspaceDraft,
  workspaceEditorController,
}: {
  type: EntityType;
  id: string;
  navigate: Navigate;
  collectionId?: string;
  onEdit?: (type: EntityType, id: string) => void;
  workspaceDraft: WorkspaceDraftController;
  workspaceEditorController: WorkspaceEditorController;
}) {
  const resource = useResource(`entity:${type}:${id}`, () => loadEntity(type, id));
  const collectionNavigation = useResource(
    `collection-navigation:${collectionId ?? ""}:${type}:${id}`,
    () => collectionId ? getCollectionNavigation(collectionId, type, id) : Promise.resolve(null),
  );
  const [annotations, setAnnotations] = useState<PresentationAnnotation[]>([]);
  const [annotationError, setAnnotationError] = useState("");
  const [annotationBusy, setAnnotationBusy] = useState(false);
  const [readerSelection, setReaderSelection] = useState<ReaderSelection | null>(null);
  const [aiSelection, setAISelection] = useState("");
  const [aiDrawerOpen, setAIDrawerOpen] = useState(false);
  const [contextExpanded, setContextExpanded] = useState(false);
  const [activeHeading, setActiveHeading] = useState("");
  const readerMarkdownRef = useRef<HTMLDivElement>(null);
  const contextPanelRef = useRef<HTMLDetailsElement>(null);
  const workspaceEnvelope = useMemo(() => splitMarkdownFrontmatter(workspaceDraft.content), [workspaceDraft.content]);
  const documentBody = type === "source" ? "" : workspaceEnvelope.body;
  const annotationsMatchCanonical = documentBody === (resource.data?.content ?? "");
  const headings = markdownHeadings(documentBody);
  const sourceIds = resource.data?.entity_type === "document"
    ? Array.from(new Set([...readList(resource.data.metadata, "sources"), ...resource.data.evidence.map((item) => item.source_id)]))
    : [];
  const sourceResource = useResource(`sources:${sourceIds.join(",")}`, () => Promise.all(sourceIds.map((sourceId) => getEntity("source", sourceId))));
  useEffect(() => {
    if (type === "document" && id) void recordDocumentOpenSafely(id);
  }, [type, id]);
  useEffect(() => {
    let active = true;
    if ((type !== "document" && type !== "term") || !resource.data) {
      setAnnotations([]);
      return () => { active = false; };
    }
    void listPresentationAnnotations(type, id)
      .then((items) => { if (active) setAnnotations(items); })
      .catch((error: unknown) => { if (active) setAnnotationError(errorMessage(error)); });
    return () => { active = false; };
  }, [type, id, resource.data?.content]);
  useEffect(() => {
    const root = readerMarkdownRef.current;
    if (!root || type === "source" || typeof IntersectionObserver === "undefined" || typeof MutationObserver === "undefined") {
      setActiveHeading("");
      return;
    }
    let observedHeadings: HTMLElement[] = [];
    let intersectionObserver: IntersectionObserver | null = null;
    const intersectingIds = new Set<string>();
    const observeHeadings = () => {
      const nextHeadings = Array.from(root.querySelectorAll<HTMLElement>("h1[id], h2[id], h3[id], h4[id], h5[id]"));
      if (nextHeadings.length === observedHeadings.length && nextHeadings.every((heading, index) => observedHeadings[index] === heading)) return;
      intersectionObserver?.disconnect();
      observedHeadings = nextHeadings;
      intersectingIds.clear();
      setActiveHeading((current) => current && observedHeadings.some((heading) => heading.id === current) ? current : observedHeadings[0]?.id ?? "");
      intersectionObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          const headingId = (entry.target as HTMLElement).id;
          if (entry.isIntersecting) intersectingIds.add(headingId);
          else intersectingIds.delete(headingId);
        });
        const currentHeading = latestIntersectingHeading(observedHeadings.map((heading) => heading.id), intersectingIds);
        if (currentHeading) setActiveHeading(currentHeading);
      }, { rootMargin: "-104px 0px -72% 0px", threshold: 0 });
      observedHeadings.forEach((heading) => intersectionObserver?.observe(heading));
    };
    const mutationObserver = new MutationObserver(observeHeadings);
    mutationObserver.observe(root, { childList: true, subtree: true });
    observeHeadings();
    return () => {
      mutationObserver.disconnect();
      intersectionObserver?.disconnect();
    };
  }, [documentBody, type]);
  if (resource.loading || workspaceDraft.loading) return <LoadingState />;
  if (workspaceDraft.loadError) return <ErrorState message={workspaceDraft.loadError} />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const entity = resource.data;
  const status = type === "source" ? readString((entity.metadata.metadata_review as Record<string, unknown> | undefined)?.status) || "unreviewed" : reviewStatus(entity);
  const evidence = entity.evidence;
  const artifacts = entity.entity_type === "document"
    ? readArtifacts(entity.metadata.external_artifacts)
    : entity.related_documents.flatMap((document) => readArtifacts(document.metadata.external_artifacts).map((artifact) => ({ ...artifact, owner: document.title })));
  const authorList = readList(entity.metadata, "authors");
  const sourceMetadata = entity.metadata;
  const identifiers = sourceMetadata.identifiers as Record<string, unknown> | undefined;
  const attachments = sourceMetadata.attachments as Record<string, unknown> | undefined;
  const localPdf = readString(attachments?.local_pdf);
  const metadataValues = [
    ["Type", typeLabel(entity)],
    ["Year", typeof sourceMetadata.year === "number" ? String(sourceMetadata.year) : ""],
    ["Human review", status],
    ["Maintenance", maintenanceStatus(entity)],
  ].filter((entry) => entry[1]);

  function captureReaderSelection(event: MouseEvent | KeyboardEvent) {
    if (event.target instanceof HTMLElement && event.target.closest(".annotation-toolbar")) return;
    const root = readerMarkdownRef.current;
    const selection = window.getSelection();
    if (!root || !selection || selection.isCollapsed || !selection.rangeCount) {
      setReaderSelection(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
      setReaderSelection(null);
      return;
    }
    const selectedText = range.toString();
    if (!selectedText || selectedText.length > 20000) {
      setReaderSelection(null);
      return;
    }
    const sourceBlockForNode = (node: Node): ReaderSourceBlock | null => {
      const element = node instanceof Element ? node : node.parentElement;
      const block = element?.closest<HTMLElement>("[data-block-index][data-source-start][data-source-end]");
      if (!block || !root.contains(block)) return null;
      const index = Number(block.dataset.blockIndex);
      const start = Number(block.dataset.sourceStart);
      const end = Number(block.dataset.sourceEnd);
      return Number.isInteger(index) && Number.isInteger(start) && Number.isInteger(end)
        ? { index, start, end }
        : null;
    };
    const sourceRange = resolveReaderSelectionSourceRange(
      selectedText,
      documentBody,
      sourceBlockForNode(range.startContainer),
      sourceBlockForNode(range.endContainer),
    );
    const rect = range.getBoundingClientRect();
    setAnnotationError("");
    setReaderSelection({
      selected_text: selectedText,
      ...sourceRange,
      top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 150)),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 576)),
    });
  }

  async function saveReaderAnnotation(styleType: AnnotationStyleType, styleValue: string | null) {
    if (!readerSelection || readerSelection.start_offset === null || readerSelection.end_offset === null || (type !== "document" && type !== "term")) return;
    setAnnotationBusy(true);
    setAnnotationError("");
    try {
      const contentHash = await hashText(documentBody);
      await createPresentationAnnotation({
        entity_type: type,
        entity_id: id,
        style_type: styleType,
        style_value: styleValue,
        selected_text: readerSelection.selected_text,
        prefix_text: documentBody.slice(Math.max(0, readerSelection.start_offset - 40), readerSelection.start_offset),
        suffix_text: documentBody.slice(readerSelection.end_offset, readerSelection.end_offset + 40),
        start_offset: readerSelection.start_offset,
        end_offset: readerSelection.end_offset,
        base_content_hash: contentHash,
      });
      setAnnotations(await listPresentationAnnotations(type, id));
      setReaderSelection(null);
      window.getSelection()?.removeAllRanges();
    } catch (error) {
      setAnnotationError(errorMessage(error));
    } finally {
      setAnnotationBusy(false);
    }
  }

  async function clearReaderAnnotations() {
    if (!readerSelection || readerSelection.start_offset === null || readerSelection.end_offset === null) return;
    const startOffset = readerSelection.start_offset;
    const endOffset = readerSelection.end_offset;
    const matching = annotations.filter((annotation) =>
      annotation.status === "active" &&
      annotation.start_offset < endOffset &&
      annotation.end_offset > startOffset,
    );
    if (!matching.length) {
      setAnnotationError("当前选区没有可清除的阅读标注。");
      return;
    }
    setAnnotationBusy(true);
    try {
      await Promise.all(matching.map((annotation) => deletePresentationAnnotation(annotation.id)));
      if (type === "document" || type === "term") setAnnotations(await listPresentationAnnotations(type, id));
      setReaderSelection(null);
      window.getSelection()?.removeAllRanges();
      setAnnotationError("");
    } catch (error) {
      setAnnotationError(errorMessage(error));
    } finally {
      setAnnotationBusy(false);
    }
  }

  function formatReaderSelection(action: MarkdownFormattingAction) {
    if (!readerSelection || readerSelection.start_offset === null || readerSelection.end_offset === null || workspaceDraft.saveState === "Conflict") return;
    try {
      const formatted = applyMarkdownFormatting(documentBody, readerSelection.start_offset, readerSelection.end_offset, action);
      workspaceDraft.updateContent(`${workspaceEnvelope.frontmatter}${formatted.value}`);
      setReaderSelection(null);
      setAnnotationError("");
      window.getSelection()?.removeAllRanges();
    } catch (error) {
      setAnnotationError(errorMessage(error));
    }
  }

  function openSelectionAI() {
    if (!readerSelection || type !== "document" || workspaceDraft.saveState === "Conflict") return;
    setAISelection(readerSelection.selected_text);
    setAIDrawerOpen(true);
    setReaderSelection(null);
    window.getSelection()?.removeAllRanges();
  }

  function toggleContextPanel() {
    setContextExpanded((expanded) => !expanded);
    contextPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function openSources() {
    setContextExpanded(true);
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      document.getElementById("reader-context-sources")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }));
  }

  return (
    <div className="page-stack entity-page">
      {collectionId && <CollectionReaderContext navigation={collectionNavigation.data} loading={collectionNavigation.loading} error={collectionNavigation.error} currentType={type} currentId={id} currentTitle={entity.title} navigate={navigate} />}
      <div className="entity-title-row">
        <div className="entity-heading"><p className="eyebrow">{typeLabel(entity).toUpperCase()}</p><h1>{entity.title}</h1><div className="entity-heading-meta"><span className="reader-entity-id">{entity.id}</span>{metadataValues.filter(([label]) => label !== "Type").map(([label, value]) => <span className="reader-header-meta" key={label}><small>{label}</small>{value}</span>)}</div></div>
      </div>
      <div className="reader-sticky-actions" role="toolbar" aria-label="阅读快捷操作">
        {onEdit && <button className="button button-secondary" onClick={() => onEdit(type, id)}>Source</button>}
        <button className="button button-secondary" onClick={() => workspaceEditorController.setActiveDrawer("metadata")}>元数据</button>
        <button className="button button-secondary" disabled={type === "source"} onClick={() => workspaceEditorController.setActiveDrawer("ai")}>AI 审阅</button>
        <button
          className="button button-secondary"
          disabled={workspaceEditorController.publishing || workspaceDraft.saveState === "Conflict" || Boolean(workspaceEditorController.publishedRevision) || (!workspaceEditorController.draft && !workspaceEditorController.isDirty)}
          onClick={() => {
            workspaceEditorController.setPublishReview(null);
            workspaceEditorController.setActiveDrawer("publish");
            void workspaceEditorController.runPreflight();
          }}
        >发布</button>
        <span className={`workspace-reader-save-state ${workspaceDraft.saveState.toLowerCase()}`} role="status">{workspaceDraft.saveState === "Ready" ? "正式版" : workspaceDraft.saveState === "Unsaved" ? "有未保存修改" : workspaceDraft.saveState === "Saving" ? "正在保存 Draft…" : workspaceDraft.saveState === "Saved" ? workspaceDraft.draft ? "Draft 已保存 · 尚未发布" : "已发布" : "Draft 冲突"}</span>
        {workspaceDraft.saveState === "Conflict" && <button className="button button-secondary" onClick={() => void workspaceEditorController.openComparison()}>处理冲突</button>}
        <button className="button button-secondary" onClick={() => navigate("/review")}>Review</button>
        {type === "document" && sourceIds.length > 0 && <button className="button button-secondary" onClick={openSources}>Sources</button>}
        <button className="button button-secondary" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Back to top</button>
        <button className="button button-secondary reader-action-more" aria-expanded={contextExpanded} aria-controls="reader-context-panel" onClick={toggleContextPanel}>{contextExpanded ? "Less" : "More"}</button>
      </div>
      <details id="reader-context-panel" ref={contextPanelRef} className="reader-context-panel surface" open={contextExpanded} onToggle={(event) => setContextExpanded(event.currentTarget.open)}>
        <summary className="reader-context-summary">
          <span className="reader-context-status"><strong>{typeLabel(entity)}</strong><span>·</span><span>{titleCase(status)}</span><span>·</span><span>{titleCase(maintenanceStatus(entity))}</span></span>
          <span className="reader-context-counts">{(type === "document" ? [`${sourceIds.length} Sources`, `${entity.related_terms.length} Terms`, `${evidence.length} Evidence`] : type === "term" ? [`${entity.backlinks.length} Backlinks`, `${entity.detected_mentions.length} Mentions`] : [`${entity.related_documents.length} Documents`, `${evidence.length} Evidence`]).map((item) => <span key={item}>{item}</span>)}</span>
          <span className="reader-context-toggle">{contextExpanded ? "收起详情" : "展开详情"}</span>
        </summary>
        <div className="reader-context-details">
          <div className="reader-context">
            {type === "document" && <ContextCard title="分类"><MetaChipList values={[...readList(entity.metadata, "domains"), ...readList(entity.metadata, "topics"), ...readList(entity.metadata, "tags")]} /></ContextCard>}
            {type === "document" && <ContextCard id="reader-context-sources" title="Sources" detail={sourceIds.length ? `${sourceIds.length} 个关联来源` : "没有关联来源"}>{sourceResource.data?.map((source) => <button className="context-link" key={source.id} onClick={() => navigate(entityPath(source))}><span className="context-icon source">S</span><span><strong>{source.title}</strong><small>{readString(source.metadata.type) || "Source"}</small></span><span>↗</span></button>)}</ContextCard>}
            <ContextCard title="Terms" detail={`${entity.related_terms.length} 个关联术语`}>{entity.related_terms.length ? entity.related_terms.map((term) => <button className="context-link" key={term.id} onClick={() => navigate(entityPath({ entity_type: "term", id: term.id }))}><span className="context-icon term">T</span><span><strong>{term.title}</strong><small>{term.id}</small></span><span>↗</span></button>) : <p className="subtle-copy">正文中的 Wiki Link 会在这里形成关系。</p>}</ContextCard>
            {type === "term" && <ContextCard title="Backlinks" detail="已正式链接到此 Term 的内容">{entity.backlinks.length ? entity.backlinks.map((backlink, index) => { const sourceType = readString(backlink.source_entity_type) === "document" ? "document" : "term"; const sourceId = readString(backlink.source_entity_id); return <button className="context-link" key={`${sourceId}:${index}`} onClick={() => navigate(`/${sourceType === "document" ? "documents" : "terms"}/${encodeURIComponent(sourceId)}`)}><span><strong>{sourceId}</strong><small>第 {String(backlink.line)} 行 · {readString(backlink.label) || readString(backlink.link_target)}</small></span><span>↗</span></button>; }) : <p className="subtle-copy">尚无内容通过 Wiki Link 指向这个 Term。</p>}</ContextCard>}
            {type === "term" && <ContextCard title="Detected Mentions" detail="文本提及尚未成为正式 Wiki Link">{entity.detected_mentions.length ? entity.detected_mentions.map((mention) => <button className="context-link" key={mention.id} onClick={() => navigate(`/documents/${encodeURIComponent(mention.id)}`)}><span><strong>{mention.title}</strong><small>{mention.id}</small></span><span>↗</span></button>) : <p className="subtle-copy">没有发现未链接的提及。</p>}</ContextCard>}
            <ContextCard title={type === "source" ? "Claims & Evidence" : "Evidence"} detail={type === "source" ? "来自关联笔记中的引用" : `${evidence.length} 条引用位置`}>
              {evidence.length ? <div className="evidence-list">{evidence.map((item, index) => <div className="evidence-item" key={`${item.source_id}:${item.line}:${index}`}><button onClick={() => navigate(`/sources/${encodeURIComponent(item.source_id)}`)}>{item.citation}</button><p>{item.claim}</p><small>{item.locator || "Locator 未提供"}{item.entity_id ? ` · ${item.entity_id}` : ""}</small></div>)}</div> : <p className="subtle-copy">正文中的 Source citation 会列在这里。</p>}
              {type === "source" && status === "verified" && <p className="trust-note">Source 元数据已标记为 verified；这不代表每条 Claim 都完成了独立证据审核。</p>}
            </ContextCard>
            {type === "source" && <ContextCard title="Related Documents" detail={`${entity.related_documents.length} 篇笔记`}>{entity.related_documents.map((document) => <button className="context-link" key={document.id} onClick={() => navigate(entityPath({ entity_type: "document", id: document.id }))}><span><strong>{document.title}</strong><small>{readString(document.metadata.type) || document.id}</small></span><span>↗</span></button>)}</ContextCard>}
            {!!artifacts.length && <ContextCard title="PaperSkill" detail="外部成品链接">{artifacts.map((artifact, index) => <a className="artifact-link" key={`${artifact.url}:${index}`} href={artifact.url} target="_blank" rel="noreferrer"><span><strong>{titleCase(artifact.variant)}{artifact.owner ? ` · ${artifact.owner}` : ""}</strong><small>{artifact.url}</small></span><span>↗</span></a>)}</ContextCard>}
            {(type === "document" || type === "source") && <ContextExportPanel targetType={type} targetId={id} />}
          </div>
        </div>
      </details>
      <div className={`reader-layout ${type === "source" ? "reader-layout-source" : ""}`}>
        <aside className="reader-outline surface">
          <span className="eyebrow">ON THIS PAGE</span>
          {headings.length ? <nav>{headings.map((heading, index) => <button className={`outline-level-${heading.level} ${activeHeading === heading.slug ? "active" : ""}`} key={`${heading.slug}:${index}`} aria-current={activeHeading === heading.slug ? "location" : undefined} onClick={() => document.getElementById(heading.slug)?.scrollIntoView({ behavior: "smooth", block: "start" })}>{heading.text}</button>)}</nav> : <p className="subtle-copy">正文暂无章节标题。</p>}
        </aside>
        <article className="reader-document">
          {type === "source" ? (
            <div className="source-description surface">
              <p>{authorList.join(", ") || "作者未填写"}{typeof sourceMetadata.year === "number" ? ` · ${sourceMetadata.year}` : ""}</p>
              <dl className="source-fields">
                {identifiers && Object.entries(identifiers).filter(([, value]) => typeof value === "string" && value).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{String(value)}</dd></div>)}
                {readString(sourceMetadata.zotero_key) && <div><dt>Zotero</dt><dd>{readString(sourceMetadata.zotero_key)}</dd></div>}
                {readString(sourceMetadata.url) && <div><dt>URL</dt><dd><a href={readString(sourceMetadata.url)} target="_blank" rel="noreferrer">{readString(sourceMetadata.url)}</a></dd></div>}
              </dl>
              <div className="attachment-note"><span className="attachment-icon">PDF</span><span><strong>{localPdf ? "本地 PDF 已关联" : "没有本地 PDF"}</strong><small>PDF 保存在本机私有存储，不进入 Git。</small></span>{localPdf && <a className="button button-secondary source-pdf-button" href={`/api/sources/${encodeURIComponent(id)}/pdf`} target="_blank" rel="noreferrer">打开 PDF</a>}</div>
            </div>
          ) : <div ref={readerMarkdownRef} className="reader-markdown-wrap" onMouseUp={captureReaderSelection} onKeyUp={captureReaderSelection}>
            <WorkspaceInlineEditor
              body={documentBody}
              annotations={annotationsMatchCanonical ? annotations : []}
              disabled={workspaceDraft.saveState === "Conflict"}
              onBodyChange={(body) => workspaceDraft.updateContent(`${workspaceEnvelope.frontmatter}${body}`)}
              onBeginEdit={() => setReaderSelection(null)}
              onNavigate={navigate}
            />
            {workspaceDraft.error && <p className="workspace-reader-save-error" role="alert">Draft 保存失败：{workspaceDraft.error}</p>}
            {readerSelection && <WorkspaceSelectionToolbar
              selectedText={readerSelection.selected_text}
              top={readerSelection.top}
              left={readerSelection.left}
              formatDisabled={workspaceDraft.saveState === "Conflict" || readerSelection.start_offset === null}
              formatDisabledReason={workspaceDraft.saveState === "Conflict" ? "请先解决 Draft 冲突。" : readerSelection.format_disabled_reason ?? undefined}
              canAnnotate={readerSelection.start_offset !== null && annotationsMatchCanonical && (type === "document" || type === "term")}
              annotationBusy={annotationBusy}
              aiDisabled={workspaceDraft.saveState === "Conflict"}
              onFormat={formatReaderSelection}
              onAnnotate={(styleType, styleValue) => void saveReaderAnnotation(styleType, styleValue)}
              onClear={() => void clearReaderAnnotations()}
              onAskAI={type === "document" ? openSelectionAI : undefined}
            />}
            {annotationError && <p className="annotation-error" role="status">{annotationError}</p>}
          </div>}
        </article>
      </div>
      {aiDrawerOpen && type === "document" && <WorkspaceSelectionAIDrawer
        selectedText={aiSelection}
        workspaceDraft={workspaceDraft}
        onClose={() => setAIDrawerOpen(false)}
      />}
      <WorkspaceEditorDrawers controller={workspaceEditorController} />
    </div>
  );
}
