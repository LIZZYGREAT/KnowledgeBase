import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { parse as parseYaml, parseDocument } from "yaml";
import {
  analyzeDocumentTerms, createPresentationAnnotation, deletePresentationAnnotation,
  getCollectionNavigation, getDocumentTermAnalysis, getEntity, listPresentationAnnotations,
  type AnnotationStyleType,
  type DocumentTermAnalysisResult, type EntityDetail, type EntityType,
  type PresentationAnnotation,
} from "../api";
import { Chip, ErrorState, LoadingState, titleCase } from "../ui";
import { errorMessage } from "../errors";
import { latestIntersectingHeading } from "../readerNavigation";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { WorkspaceInlineEditor } from "../workspace/WorkspaceInlineEditor";
import { TermLanguageCard } from "./TermLanguageCard";
import { WorkspaceSelectionToolbar } from "../workspace/WorkspaceSelectionToolbar";
import { WorkspaceSelectionAIDrawer } from "../workspace/WorkspaceSelectionAIDrawer";
import { applyMarkdownFormatting, type MarkdownFormattingAction } from "../markdownFormatting";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import type { WorkspaceEditorController } from "../workspace/useWorkspaceEditorController";
import { WorkspaceEditorDrawers } from "../workspace/WorkspaceEditorDrawers";
import { CollectionReaderContext, ContextCard, ContextExportPanel, MetaChipList } from "./ReaderContext";
import { maintenanceStatus, readList, readString, reviewStatus, typeLabel, entityPath, useResource, type Navigate } from "../pages/PageShared";
import { combineDocumentTerms, hashText, markdownHeadings, readArtifacts, recordDocumentOpenSafely, resolveReaderSelectionSourceRange, type ReaderSelection, type ReaderSourceBlock } from "./readerModel";
export function EntityPage({
  type,
  id,
  navigate,
  collectionId,
  workspaceDraft,
  workspaceEditorController,
}: {
  type: EntityType;
  id: string;
  navigate: Navigate;
  collectionId?: string;
  workspaceDraft: WorkspaceDraftController;
  workspaceEditorController: WorkspaceEditorController;
}) {
  const canonicalEntity = workspaceDraft.canonicalEntity;
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
  const [analysisDialogOpen, setAnalysisDialogOpen] = useState(false);
  const [analysisConsent, setAnalysisConsent] = useState(false);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisResult, setAnalysisResult] = useState<DocumentTermAnalysisResult["statistics"] | null>(null);
  const [activeHeading, setActiveHeading] = useState("");
  const [showBackToTop, setShowBackToTop] = useState(false);
  const readerMarkdownRef = useRef<HTMLDivElement>(null);
  const contextPanelRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const updateVisibility = () => setShowBackToTop(window.scrollY > 480);
    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    return () => window.removeEventListener("scroll", updateVisibility);
  }, []);
  const workspaceEnvelope = useMemo(() => splitMarkdownFrontmatter(workspaceDraft.content), [workspaceDraft.content]);
  const draftOnlyEntity = useMemo(() => {
    if (canonicalEntity || !workspaceDraft.draft) return null;
    return makeDraftReaderEntity(type, id, workspaceDraft.content);
  }, [canonicalEntity, id, type, workspaceDraft.content, workspaceDraft.draft]);
  const currentEntity = canonicalEntity ?? draftOnlyEntity;
  const hasUnpublishedDraft = Boolean(workspaceDraft.draft || workspaceDraft.isDirty);
  const draftTitle = hasUnpublishedDraft ? readDraftTitle(workspaceDraft.content, type) : null;
  const displayTitle = hasUnpublishedDraft && draftTitle?.valid
    ? draftTitle.title
    : currentEntity?.title ?? "";
  const hasDraftConflict = workspaceDraft.saveState === "runtime-conflict"
    || workspaceDraft.saveState === "canonical-conflict";
  const discardBlocked = workspaceDraft.saveState === "saving" || hasDraftConflict;
  const saveStateLabel = workspaceDraft.saveState === "clean" ? "正式版"
    : workspaceDraft.saveState === "unsaved" ? "有未保存修改"
      : workspaceDraft.saveState === "saving" ? "正在保存 Draft…"
        : workspaceDraft.saveState === "saved" ? workspaceDraft.draft ? "Draft 已保存 · 尚未发布" : "已发布"
          : workspaceDraft.saveState === "loading" ? "正在载入 Draft…"
            : workspaceDraft.saveState === "error" ? "Draft 状态出错"
              : "Draft 冲突";
  const documentBody = type === "source" ? "" : workspaceEnvelope.body;
  const annotationsMatchCanonical = Boolean(canonicalEntity) && documentBody === (canonicalEntity?.content ?? "");
  const headings = markdownHeadings(documentBody);
  const sourceIds = currentEntity?.entity_type === "document"
    ? Array.from(new Set([...readList(currentEntity.metadata, "sources"), ...currentEntity.evidence.map((item) => item.source_id)]))
    : [];
  const sourceResource = useResource(`sources:${sourceIds.join(",")}`, () => Promise.all(sourceIds.map((sourceId) => getEntity("source", sourceId))));
  const termAnalysisResource = useResource(
    `document-term-analysis:${id}`,
    () => type === "document" ? getDocumentTermAnalysis(id) : Promise.resolve(null),
  );
  const termWhereAppears = useMemo(() => {
    if (currentEntity?.entity_type !== "term") return [];
    const byEntity = new Map<string, { id: string; title: string; entityType: "document" | "source" | "research_work"; labels: Set<string>; details: Set<string> }>();
    for (const relation of currentEntity.term_relations ?? []) {
      const key = `${relation.entity_type}:${relation.entity_id}`;
      const item = byEntity.get(key) ?? {
        id: relation.entity_id,
        title: relation.title || relation.entity_id,
        entityType: relation.entity_type,
        labels: new Set<string>(),
        details: new Set<string>(),
      };
      item.labels.add(relation.entity_type === "source" ? "Accepted Source relation" : "Accepted detection");
      byEntity.set(key, item);
    }
    for (const backlink of currentEntity.backlinks) {
      if (readString(backlink.source_entity_type) !== "document") continue;
      const documentId = readString(backlink.source_entity_id);
      if (!documentId) continue;
      const key = `document:${documentId}`;
      const item = byEntity.get(key) ?? {
        id: documentId,
        title: readString(backlink.source_title) || documentId,
        entityType: "document" as const,
        labels: new Set<string>(),
        details: new Set<string>(),
      };
      item.labels.add("Explicit link");
      const line = typeof backlink.line === "number" ? String(backlink.line) : readString(backlink.line);
      const label = readString(backlink.label) || readString(backlink.link_target);
      if (line || label) item.details.add([line ? `第 ${line} 行` : "", label].filter(Boolean).join(" · "));
      byEntity.set(key, item);
    }
    return Array.from(byEntity.values()).sort((left, right) => left.title.localeCompare(right.title));
  }, [currentEntity]);
  const documentTerms = useMemo(() => currentEntity?.entity_type === "document"
    ? combineDocumentTerms(
      currentEntity.related_terms,
      currentEntity.term_relations ?? [],
      currentEntity.id,
    )
    : [], [currentEntity]);
  useEffect(() => {
    if (type === "document" && id) void recordDocumentOpenSafely(id);
  }, [type, id]);
  useEffect(() => {
    if (type === "document" && workspaceDraft.publishedRevision) {
      setAnalysisResult(null);
      termAnalysisResource.retry();
    }
  }, [type, workspaceDraft.publishedRevision]);
  useEffect(() => {
    let active = true;
    if ((type !== "document" && type !== "term") || !canonicalEntity) {
      setAnnotations([]);
      return () => { active = false; };
    }
    void listPresentationAnnotations(type, id)
      .then((items) => { if (active) setAnnotations(items); })
      .catch((error: unknown) => { if (active) setAnnotationError(errorMessage(error)); });
    return () => { active = false; };
  }, [type, id, canonicalEntity?.content]);
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
  if (workspaceDraft.loading) return <LoadingState />;
  if (workspaceDraft.loadError) return <ErrorState message={workspaceDraft.loadError} retry={workspaceDraft.retryCanonicalEntity} />;
  if (!currentEntity) return <ErrorState message="无法载入 Canonical Entity。" retry={workspaceDraft.retryCanonicalEntity} />;
  const entity = currentEntity;
  const contextTerms = type === "document"
    ? documentTerms
    : entity.related_terms.map((term) => ({ id: term.id, title: term.title, labels: [] as string[] }));
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
    if (!readerSelection || readerSelection.start_offset === null || readerSelection.end_offset === null || hasDraftConflict) return;
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
    if (!readerSelection || type !== "document" || hasDraftConflict) return;
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

  async function analyzeCanonicalDocumentTerms() {
    if (type !== "document" || !analysisConsent || analysisBusy || workspaceDraft.draft || workspaceDraft.isDirty) return;
    setAnalysisBusy(true);
    setAnalysisError("");
    try {
      const result = await analyzeDocumentTerms(id);
      setAnalysisResult(result.statistics);
      setAnalysisDialogOpen(false);
      setAnalysisConsent(false);
      termAnalysisResource.retry();
    } catch (reason) {
      setAnalysisError(errorMessage(reason));
    } finally {
      setAnalysisBusy(false);
    }
  }

  return (
    <div className="page-stack entity-page">
      {collectionId && <CollectionReaderContext navigation={collectionNavigation.data} loading={collectionNavigation.loading} error={collectionNavigation.error} currentType={type} currentId={id} currentTitle={displayTitle} navigate={navigate} />}
      <div className="entity-title-row">
        <div className="entity-heading"><p className="eyebrow">{typeLabel(entity).toUpperCase()}</p><h1>{displayTitle}</h1>{hasUnpublishedDraft && <span className="entity-draft-preview-label" role="status">Draft 预览 · 尚未发布</span>}{hasUnpublishedDraft && draftTitle && !draftTitle.valid && <p className="entity-draft-title-error" role="alert">Draft 标题无法读取，仍显示正式标题。请先修复元数据 YAML。</p>}<div className="entity-heading-meta"><span className="reader-entity-id">{entity.id}</span>{metadataValues.filter(([label]) => label !== "Type").map(([label, value]) => <span className="reader-header-meta" key={label}><small>{label}</small>{value}</span>)}</div></div>
      </div>
      <div className="reader-sticky-actions" role="toolbar" aria-label="阅读快捷操作">
        <div className="reader-toolbar-group" role="group" aria-label="编辑">
          <button className="button button-secondary" onClick={() => workspaceEditorController.setActiveDrawer("source")}>Source</button>
          <button className="button button-secondary" onClick={() => workspaceEditorController.setActiveDrawer("metadata")}>元数据</button>
          <button className="button button-secondary" disabled={type === "source"} onClick={() => workspaceEditorController.setActiveDrawer("ai")}>AI 审阅</button>
          <button
            className="button button-secondary"
            disabled={workspaceEditorController.publishing || hasDraftConflict || Boolean(workspaceEditorController.publishedRevision) || (!workspaceEditorController.draft && !workspaceEditorController.isDirty)}
            onClick={() => {
              workspaceEditorController.setPublishReview(null);
              workspaceEditorController.setActiveDrawer("publish");
              void workspaceEditorController.runPreflight();
            }}
          >{workspaceEditorController.batchCollectionId || workspaceEditorController.additionalDraftIds.length ? "Publish All" : "发布"}</button>
          {workspaceEditorController.draft && <button
            className="button button-danger"
            disabled={workspaceEditorController.publishing || discardBlocked}
            title={discardBlocked ? "请等待保存完成或先处理冲突" : undefined}
            aria-describedby={discardBlocked ? "reader-discard-disabled-reason" : undefined}
            onClick={() => void workspaceEditorController.discardCurrentDraft()}
          >{workspaceEditorController.batchCollectionId || workspaceEditorController.researchGroupId ? "丢弃笔记并撤销引用" : "丢弃 Draft"}</button>}
        </div>
        <div className="reader-toolbar-group reader-toolbar-status" role="group" aria-label="状态">
          {discardBlocked && <span id="reader-discard-disabled-reason" className="subtle-copy" role="status">请等待保存完成或先处理冲突</span>}
          <span className={`workspace-reader-save-state ${hasDraftConflict ? "conflict" : workspaceDraft.saveState}`} role="status">{saveStateLabel}</span>
          {workspaceDraft.saveState === "canonical-conflict" && <button className="button button-secondary" onClick={() => void workspaceEditorController.openComparison()}>处理冲突</button>}
        </div>
        <div className="reader-toolbar-group reader-toolbar-reading" role="group" aria-label="阅读">
          <button className="button button-secondary" onClick={() => navigate("/review")}>Review</button>
          {type === "document" && sourceIds.length > 0 && <button className="button button-secondary" onClick={openSources}>Sources</button>}
          <button className="button button-secondary reader-action-more" aria-expanded={contextExpanded} aria-controls="reader-context-panel" onClick={toggleContextPanel}>{contextExpanded ? "Less" : "More"}</button>
        </div>
      </div>
      {workspaceDraft.error && workspaceEditorController.activeDrawer !== "metadata" && <p className="workspace-reader-save-error" role="alert">保存失败：{workspaceDraft.error}</p>}
      {type === "document" && canonicalEntity && <section className="term-analysis-panel surface" aria-labelledby="term-analysis-title">
        <div className="term-analysis-copy"><div className="term-analysis-heading"><strong id="term-analysis-title">Term Analysis</strong><Chip tone={termAnalysisResource.data?.status === "up_to_date" ? "green" : termAnalysisResource.data?.status === "outdated" ? "amber" : "neutral"}>{analysisBusy ? "Analyzing" : termAnalysisResource.loading ? "Checking status…" : termAnalysisResource.data?.status === "up_to_date" ? "Up to date" : termAnalysisResource.data?.status === "outdated" ? "Outdated" : "Never analyzed"}</Chip></div>
          <p>{workspaceDraft.draft || workspaceDraft.isDirty ? "当前存在未发布 Draft；Term Analysis 只读取 Canonical 正式内容，请先发布或处理 Draft。" : "手动分析 Canonical Note 中值得长期复用的 Terms；不会分析 Draft，也不会在发布时自动运行。"}</p>
          {analysisResult && <small role="status">最近一次分析：新增 {analysisResult.created_candidates}，复用 {analysisResult.reused_candidates}，Existing {analysisResult.existing}，New {analysisResult.new}，跳过 {analysisResult.skipped}。</small>}
          {termAnalysisResource.error && <small className="term-analysis-error" role="status">状态读取失败：{termAnalysisResource.error}</small>}
          {analysisError && <small className="term-analysis-error" role="status">分析失败：{analysisError}</small>}
        </div>
        <div className="term-analysis-actions"><button className="button button-secondary" type="button" onClick={() => navigate(`/terms?tab=candidates&document_id=${encodeURIComponent(id)}`)}>View Candidates</button><button className="button button-primary" type="button" disabled={analysisBusy || termAnalysisResource.loading || Boolean(workspaceDraft.draft || workspaceDraft.isDirty)} onClick={() => { setAnalysisError(""); setAnalysisConsent(false); setAnalysisDialogOpen(true); }}>{analysisBusy ? "Analyzing…" : termAnalysisResource.data?.status === "never_analyzed" || !termAnalysisResource.data ? "Analyze Terms" : "Analyze Again"}</button></div>
      </section>}
      <details id="reader-context-panel" ref={contextPanelRef} className="reader-context-panel surface" open={contextExpanded} onToggle={(event) => setContextExpanded(event.currentTarget.open)}>
        <summary className="reader-context-summary">
          <span className="reader-context-status"><strong>{typeLabel(entity)}</strong><span>·</span><span>{titleCase(status)}</span><span>·</span><span>{titleCase(maintenanceStatus(entity))}</span></span>
          <span className="reader-context-counts">{(type === "document" ? [`${sourceIds.length} Sources`, `${documentTerms.length} Terms`, `${evidence.length} Evidence`] : type === "term" ? [`${termWhereAppears.length} Where it appears`, `${entity.detected_mentions.length} Detected mentions`] : [`${entity.related_documents.length} Documents`, `${evidence.length} Evidence`]).map((item) => <span key={item}>{item}</span>)}</span>
          <span className="reader-context-toggle">{contextExpanded ? "收起详情" : "展开详情"}</span>
        </summary>
        <div className="reader-context-details">
          <div className="reader-context">
            {type === "document" && <ContextCard title="分类"><MetaChipList values={[...readList(entity.metadata, "domains"), ...readList(entity.metadata, "topics"), ...readList(entity.metadata, "tags")]} /></ContextCard>}
            {type === "document" && <ContextCard id="reader-context-sources" title="Sources" detail={sourceIds.length ? `${sourceIds.length} 个关联来源` : "没有关联来源"}>{sourceResource.data?.map((source) => <button className="context-link" key={source.id} onClick={() => navigate(entityPath(source))}><span className="context-icon source">S</span><span><strong>{source.title}</strong><small>{readString(source.metadata.type) || "Source"}</small></span><span>↗</span></button>)}</ContextCard>}
            <ContextCard title="Terms" detail={`${contextTerms.length} 个关联术语`}>{contextTerms.length ? contextTerms.map((term) => <button className="context-link" key={term.id} onClick={() => navigate(entityPath({ entity_type: "term", id: term.id }))}><span className="context-icon term">T</span><span><strong>{term.title}</strong><small>{[term.id, ...term.labels].join(" · ")}</small></span><span>↗</span></button>) : <p className="subtle-copy">{type === "document" ? "显式 Wiki Link 与已接受的检测关系会在这里显示。" : "正文中的 Wiki Link 会在这里形成关系。"}</p>}</ContextCard>
            {type === "term" && <ContextCard title="Where it appears" detail="区分正文显式链接、已接受的 Term 关系以及 Source 和 Research 记录">{termWhereAppears.length ? termWhereAppears.map((item) => <button className="context-link term-appearance-link" key={`${item.entityType}:${item.id}`} onClick={() => navigate(item.entityType === "document" ? `/documents/${encodeURIComponent(item.id)}` : item.entityType === "source" ? `/sources/${encodeURIComponent(item.id)}` : `/research?work_id=${encodeURIComponent(item.id)}`)}><span><strong>{item.title}</strong><small>{`${titleCase(item.entityType.replace("_", " "))} · ${Array.from(item.labels).join(" · ")}`}</small>{item.details.size > 0 && <small>{Array.from(item.details).join(" · ")}</small>}</span><span>↗</span></button>) : <p className="subtle-copy">还没有显式链接或已接受的 Term 关系。</p>}</ContextCard>}
            {type === "term" && <ContextCard title="Term backlinks" detail="其他 Term 正文中的 Wiki Link">{entity.backlinks.filter((backlink) => readString(backlink.source_entity_type) === "term").length ? entity.backlinks.filter((backlink) => readString(backlink.source_entity_type) === "term").map((backlink, index) => { const sourceId = readString(backlink.source_entity_id); return <button className="context-link" key={`${sourceId}:${index}`} onClick={() => navigate(`/terms/${encodeURIComponent(sourceId)}`)}><span><strong>{readString(backlink.source_title) || sourceId}</strong><small>{sourceId} · 第 {String(backlink.line)} 行 · {readString(backlink.label) || readString(backlink.link_target)}</small></span><span>↗</span></button>; }) : <p className="subtle-copy">没有其他 Term 链接到此条目。</p>}</ContextCard>}
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
      <div className={`reader-layout ${type !== "document" ? "reader-layout-source" : ""}`}>
        {type === "document" && <details className="reader-outline surface" open>
          <summary><span className="eyebrow">目录</span></summary>
          {headings.length ? <nav>{headings.map((heading, index) => <button className={`outline-level-${heading.level} ${activeHeading === heading.slug ? "active" : ""}`} key={`${heading.slug}:${index}`} aria-current={activeHeading === heading.slug ? "location" : undefined} onClick={() => document.getElementById(heading.slug)?.scrollIntoView({ behavior: "smooth", block: "start" })}>{heading.text}</button>)}</nav> : <p className="subtle-copy">正文暂无章节标题。</p>}
        </details>}
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
          ) : type === "term" ? <TermLanguageCard body={documentBody} workspace={workspaceDraft} navigate={navigate} disabled={hasDraftConflict} /> : <div ref={readerMarkdownRef} className="reader-markdown-wrap" onMouseUp={captureReaderSelection} onKeyUp={captureReaderSelection}>
            <WorkspaceInlineEditor
              body={documentBody}
              annotations={annotationsMatchCanonical ? annotations : []}
              disabled={hasDraftConflict}
              onBodyChange={(body) => workspaceDraft.updateContent(`${workspaceEnvelope.frontmatter}${body}`)}
              onBeginEdit={() => setReaderSelection(null)}
              onNavigate={navigate}
            />
            {readerSelection && <WorkspaceSelectionToolbar
              selectedText={readerSelection.selected_text}
              top={readerSelection.top}
              left={readerSelection.left}
              formatDisabled={hasDraftConflict || readerSelection.start_offset === null}
              formatDisabledReason={hasDraftConflict ? "请先解决 Draft 冲突。" : readerSelection.format_disabled_reason ?? undefined}
              canAnnotate={readerSelection.start_offset !== null && annotationsMatchCanonical && (type === "document" || type === "term")}
              annotationBusy={annotationBusy}
              aiDisabled={hasDraftConflict}
              onFormat={formatReaderSelection}
              onAnnotate={(styleType, styleValue) => void saveReaderAnnotation(styleType, styleValue)}
              onClear={() => void clearReaderAnnotations()}
              onAskAI={type === "document" ? openSelectionAI : undefined}
            />}
            {annotationError && <p className="annotation-error" role="status">{annotationError}</p>}
          </div>}
        </article>
      </div>
      {showBackToTop && <button className="button button-secondary reader-back-to-top" type="button" aria-label="回到顶部" title="回到顶部" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><span aria-hidden="true">↑</span>回到顶部</button>}
      {analysisDialogOpen && type === "document" && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !analysisBusy) setAnalysisDialogOpen(false); }}>
        <section className="explorer-modal term-analysis-dialog surface" role="dialog" aria-modal="true" aria-labelledby="term-analysis-consent-title">
          <div className="section-heading"><div><h2 id="term-analysis-consent-title">分析 Canonical Note</h2><p>Term Analysis 只使用当前已发布的正式内容。</p></div><button className="text-button" type="button" disabled={analysisBusy} onClick={() => setAnalysisDialogOpen(false)}>关闭</button></div>
          <div className="term-analysis-transfer-copy"><p>本次会向 DeepSeek 发送这篇 Note 的正文和必要元数据、当前 Term Registry，以及该 Note 适用的拒绝记录，用于识别可复用概念、命名实体和阅读词汇。</p><p>不会发送其他 Notes 的全文，也不会自动把发现写入 Markdown；结果会进入 Candidates 等待审核。</p></div>
          <label className="ai-consent"><input type="checkbox" checked={analysisConsent} onChange={(event) => setAnalysisConsent(event.target.checked)} /><span>我同意将以上 Canonical Note 内容和所需 Registry 上下文发送给 DeepSeek。</span></label>
          {analysisError && <p className="error-copy" role="alert">{analysisError}</p>}
          <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={analysisBusy} onClick={() => setAnalysisDialogOpen(false)}>取消</button><button className="button button-primary" type="button" disabled={!analysisConsent || analysisBusy || Boolean(workspaceDraft.draft || workspaceDraft.isDirty)} onClick={() => void analyzeCanonicalDocumentTerms()}>{analysisBusy ? "Analyzing…" : "同意并分析"}</button></div>
        </section>
      </div>}
      {aiDrawerOpen && type === "document" && <WorkspaceSelectionAIDrawer
        selectedText={aiSelection}
        workspaceDraft={workspaceDraft}
        onClose={() => setAIDrawerOpen(false)}
      />}
      <WorkspaceEditorDrawers controller={workspaceEditorController} />
    </div>
  );
}

function makeDraftReaderEntity(type: EntityType, id: string, content: string): EntityDetail {
  const envelope = splitMarkdownFrontmatter(content);
  const yamlText = envelope.frontmatter
    ? envelope.frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, "")
    : type === "source" ? content : "";
  let metadata: Record<string, unknown> = {};
  try {
    const value: unknown = yamlText ? parseYaml(yamlText) : {};
    if (value && typeof value === "object" && !Array.isArray(value)) {
      metadata = value as Record<string, unknown>;
    }
  } catch {
    metadata = {};
  }
  return {
    id,
    title: typeof metadata.title === "string" ? metadata.title : "",
    entity_type: type,
    metadata,
    content: type === "source" ? null : envelope.body,
    canonical_content: null,
    related_terms: [],
    backlinks: [],
    detected_mentions: [],
    evidence: [],
    related_documents: [],
  };
}

function readDraftTitle(content: string, type: EntityType): { valid: true; title: string } | { valid: false } {
  const envelope = splitMarkdownFrontmatter(content);
  const yamlText = type === "source"
    ? content
    : envelope.frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, "");
  if (!yamlText.trim()) return { valid: false };
  try {
    const document = parseDocument(yamlText);
    if (document.errors.length) return { valid: false };
    const metadata: unknown = document.toJS();
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return { valid: false };
    const title = (metadata as Record<string, unknown>).title;
    return typeof title === "string" ? { valid: true, title } : { valid: false };
  } catch {
    return { valid: false };
  }
}
