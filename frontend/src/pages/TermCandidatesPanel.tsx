import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  acceptTermCandidate,
  createCandidateTermDraft,
  deleteTermCandidate,
  getDraft,
  listTermCandidates,
  rejectTermCandidate,
  restoreTermCandidate,
  type Draft,
  type EntitySummary,
  type TermCandidate,
  type TermType,
} from "../api";
import { errorMessage } from "../errors";
import { Chip, EmptyState, ErrorState, LoadingState, titleCase } from "../ui";
import { TermCandidateReview } from "./TermCandidateReview";
import { termTypeLabel } from "../termLabels";
import { readList, readString, useResource, type Navigate, type SelectEntity } from "./PageShared";

type OriginFilter = "all" | "notes" | "pdf" | "research" | "web";
type ResolutionFilter = "all" | "existing" | "new";

export function TermCandidatesPanel({
  terms,
  onOpen,
  navigate,
  initialDocumentId = "",
}: {
  terms: EntitySummary[];
  onOpen: SelectEntity;
  navigate: Navigate;
  initialDocumentId?: string;
}) {
  const resource = useResource("term-candidates", listTermCandidates);
  const [originFilter, setOriginFilter] = useState<OriginFilter>(initialDocumentId ? "notes" : "all");
  const [documentFilter, setDocumentFilter] = useState(initialDocumentId);
  const [termTypeFilter, setTermTypeFilter] = useState<TermType | "">("");
  const [showRejected, setShowRejected] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [publishWarnings, setPublishWarnings] = useState<string[]>([]);
  const [deleteConfirmation, setDeleteConfirmation] = useState<TermCandidate[] | null>(null);
  const [resolutionFilter, setResolutionFilter] = useState<ResolutionFilter>("all");
  const [busyCandidateId, setBusyCandidateId] = useState("");
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, Draft>>({});
  const [pickerCandidate, setPickerCandidate] = useState<TermCandidate | null>(null);
  const [selectedTermId, setSelectedTermId] = useState("");
  const [termQuery, setTermQuery] = useState("");
  const [activeReviewId, setActiveReviewId] = useState("");
  const activeReviewIdRef = useRef(activeReviewId);
  activeReviewIdRef.current = activeReviewId;
  const panelRef = useRef<HTMLElement | null>(null);
  const reviewRefs = useRef(new Map<string, HTMLDivElement>());
  const reviewRefCallbacks = useRef(new Map<string, (node: HTMLDivElement | null) => void>());
  const reviewReturnFocusRefs = useRef(new Map<string, HTMLButtonElement>());
  const pickerReturnFocusRef = useRef<HTMLElement | null>(null);
  const pickerSearchRef = useRef<HTMLInputElement | null>(null);

  function reviewRefFor(candidateId: string) {
    let callback = reviewRefCallbacks.current.get(candidateId);
    if (!callback) {
      callback = (node) => {
        if (!node) {
          reviewRefs.current.delete(candidateId);
          reviewRefCallbacks.current.delete(candidateId);
          return;
        }
        reviewRefs.current.set(candidateId, node);
        if (activeReviewIdRef.current === candidateId) {
          node.scrollIntoView?.({ block: "start", behavior: "smooth" });
          node.focus({ preventScroll: true });
        }
      };
      reviewRefCallbacks.current.set(candidateId, callback);
    }
    return callback;
  }

  useLayoutEffect(() => {
    const review = activeReviewId ? reviewRefs.current.get(activeReviewId) : null;
    if (!review) return;
    review.scrollIntoView?.({ block: "start", behavior: "smooth" });
    review.focus({ preventScroll: true });
  }, [activeReviewId]);

  useEffect(() => {
    if (pickerCandidate) {
      pickerSearchRef.current?.focus();
      return;
    }
    const returnFocus = pickerReturnFocusRef.current;
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    else panelRef.current?.focus({ preventScroll: true });
  }, [pickerCandidate]);

  useEffect(() => {
    setOriginFilter(initialDocumentId ? "notes" : "all");
    setDocumentFilter(initialDocumentId);
  }, [initialDocumentId]);

  const candidates = resource.data ?? [];
  const documents = useMemo(() => {
    const byId = new Map<string, string>();
    for (const candidate of candidates) {
      for (const item of candidate.evidence) {
        if (item.origin_type === "document") {
          byId.set(item.origin_id, item.origin_title || item.origin_id);
        }
      }
    }
    return Array.from(byId, ([id, title]) => ({ id, title })).sort((left, right) =>
      left.title.localeCompare(right.title),
    );
  }, [candidates]);
  const visibleCandidates = candidates.filter((candidate) => {
    if (showRejected ? candidate.status !== "rejected" : candidate.status !== "pending" && candidate.status !== "drafting") return false;
    const originType = originFilter === "notes" ? "document"
      : originFilter === "pdf" ? "source"
        : originFilter === "research" ? "research_work"
          : originFilter === "web" ? "external"
            : null;
    if (originType && !candidate.evidence.some((item) => item.origin_type === originType)) return false;
    if (documentFilter && !candidate.evidence.some((item) => item.origin_type === "document" && item.origin_id === documentFilter)) return false;
    if (termTypeFilter && candidate.suggested_type !== termTypeFilter) return false;
    if (resolutionFilter === "existing" && !candidate.suggested_term_id) return false;
    if (resolutionFilter === "new" && candidate.suggested_term_id) return false;
    return true;
  });
  const pickerTerms = terms.filter((term) => {
    const query = termQuery.trim().toLocaleLowerCase();
    if (!query) return true;
    return [term.id, term.title, ...readList(term.metadata, "aliases")]
      .some((value) => value.toLocaleLowerCase().includes(query));
  });
  const duplicateGroups = Object.values(visibleCandidates.reduce<Record<string, TermCandidate[]>>((groups, candidate) => { (groups[candidate.normalized_name] ??= []).push(candidate); return groups; }, {})).filter((items) => items.length > 1);
  const selectedOpen = visibleCandidates.filter((candidate) => candidate.status === "pending" && selected.includes(candidate.id));
  const openCandidateCount = candidates.filter((candidate) => candidate.status === "pending" || candidate.status === "drafting").length;
  const displayedCandidateCount = visibleCandidates.length;

  async function rejectSelected() {
    setBatchBusy(true);
    try {
      for (const candidate of selectedOpen) {
        const succeeded = await runAction(candidate.id, () => rejectTermCandidate(candidate.id, { scope: "global" }));
        if (succeeded) setSelected((current) => current.filter((id) => id !== candidate.id));
      }
    } finally { setBatchBusy(false); }
  }

  function askToDelete(items: TermCandidate[]) {
    if (items.length) setDeleteConfirmation(items);
  }

  async function confirmDelete() {
    if (!deleteConfirmation?.length) return;
    setBatchBusy(true);
    const targets = deleteConfirmation;
    const outcomes = await Promise.all(targets.map(async (candidate) => {
      try {
        await deleteTermCandidate(candidate.id);
        return { candidate, error: "" };
      } catch (reason) {
        return { candidate, error: errorMessage(reason) };
      }
    }));
    const succeededIds = new Set(outcomes.filter((item) => !item.error).map((item) => item.candidate.id));
    const failed = outcomes.filter((item) => item.error);
    setSelected((current) => current.filter((id) => !succeededIds.has(id)));
    setActionErrors((current) => {
      const next = { ...current };
      for (const item of outcomes) {
        if (item.error) next[item.candidate.id] = item.error;
        else delete next[item.candidate.id];
      }
      return next;
    });
    if (targets.length === 1) {
      const item = outcomes[0];
      setNotice(item.error
        ? `无法删除“${item.candidate.display_name}”：${item.error}`
        : `已删除“${item.candidate.display_name}”；未加入拒绝历史。`);
    } else {
      const failureDetails = failed.map((item) => `${item.candidate.display_name}：${item.error}`).join("；");
      setNotice(`批量暂时移除完成：成功 ${outcomes.length - failed.length} 项，失败 ${failed.length} 项。${failureDetails ? `失败详情：${failureDetails}` : ""}`);
    }
    setDeleteConfirmation(null);
    setBatchBusy(false);
    if (succeededIds.size) resource.retry();
  }

  async function runAction(candidateId: string, action: () => Promise<unknown>): Promise<boolean> {
    setBusyCandidateId(candidateId);
    setActionErrors((current) => ({ ...current, [candidateId]: "" }));
    try {
      await action();
      resource.retry();
      return true;
    } catch (reason) {
      setActionErrors((current) => ({ ...current, [candidateId]: errorMessage(reason) }));
      return false;
    } finally {
      setBusyCandidateId("");
    }
  }

  function openTermPicker(candidate: TermCandidate, trigger: HTMLButtonElement) {
    pickerReturnFocusRef.current = trigger;
    setPickerCandidate(candidate);
    setSelectedTermId(candidate.suggested_term_id ?? "");
    setTermQuery("");
  }

  async function linkCandidateToSelectedTerm() {
    if (!pickerCandidate || !selectedTermId) return;
    const succeeded = await runAction(pickerCandidate.id, () =>
      acceptTermCandidate(pickerCandidate.id, selectedTermId),
    );
    if (succeeded) setPickerCandidate(null);
  }

  async function openCandidateDraft(candidate: TermCandidate, trigger: HTMLButtonElement) {
    if (!candidate.draft_id) return;
    reviewReturnFocusRefs.current.set(candidate.id, trigger);
    setBusyCandidateId(candidate.id);
    setActionErrors((current) => ({ ...current, [candidate.id]: "" }));
    try {
      const draft = await getDraft(candidate.draft_id);
      setReviewDrafts((current) => ({ ...current, [candidate.id]: draft }));
      setActiveReviewId(candidate.id);
    } catch (reason) {
      setActionErrors((current) => ({ ...current, [candidate.id]: errorMessage(reason) }));
      resource.retry();
    } finally {
      setBusyCandidateId("");
    }
  }

  function startCreate(candidate: TermCandidate, trigger: HTMLButtonElement) {
    reviewReturnFocusRefs.current.set(candidate.id, trigger);
    void runAction(candidate.id, async () => {
      const result = await createCandidateTermDraft(candidate.id);
      setReviewDrafts((current) => ({ ...current, [candidate.id]: result.draft }));
      setActiveReviewId(candidate.id);
    });
  }

  function returnFromReview(candidateId: string) {
    const trigger = reviewReturnFocusRefs.current.get(candidateId);
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    else panelRef.current?.focus({ preventScroll: true });
    reviewReturnFocusRefs.current.delete(candidateId);
    setActiveReviewId((current) => current === candidateId ? "" : current);
    setReviewDrafts((current) => { const next = { ...current }; delete next[candidateId]; return next; });
  }

  function selectOriginFilter(filter: OriginFilter) {
    setOriginFilter(filter);
    if (filter !== "notes") setDocumentFilter("");
  }

  return (
    <section ref={panelRef} tabIndex={-1} className="term-candidates-panel" aria-label="待处理术语">
      <header className="term-candidate-page-heading">
        <div><h2>待处理术语</h2><p>{showRejected ? "查看已拒绝的候选及其拒绝历史。" : "判断候选术语，编辑解释或关联已有术语。"}</p></div>
        <div className="term-candidate-page-summary">
          <span className="count-label">{showRejected ? `${displayedCandidateCount} 条拒绝记录` : `显示 ${displayedCandidateCount} / 待审 ${openCandidateCount}`}</span>
          <button className="button button-quiet" type="button" onClick={() => { setShowRejected(!showRejected); setSelected([]); }}>{showRejected ? "返回待审" : "拒绝历史"}</button>
        </div>
      </header>
      <div className="term-candidate-toolbar surface" aria-label="候选筛选">
        <div className="term-candidate-origin-filter">
          <div className="segmented-control" role="group" aria-label="候选来源">
            <button type="button" aria-pressed={originFilter === "all"} className={originFilter === "all" ? "active" : ""} onClick={() => selectOriginFilter("all")}>全部</button>
            <button type="button" aria-pressed={originFilter === "notes"} className={originFilter === "notes" ? "active" : ""} onClick={() => selectOriginFilter("notes")}>笔记</button>
            <button type="button" aria-pressed={originFilter === "pdf"} className={originFilter === "pdf" ? "active" : ""} onClick={() => selectOriginFilter("pdf")}>PDF</button>
            <button type="button" aria-pressed={originFilter === "research"} className={originFilter === "research" ? "active" : ""} onClick={() => selectOriginFilter("research")}>论文推荐</button>
            <button type="button" aria-pressed={originFilter === "web"} className={originFilter === "web" ? "active" : ""} onClick={() => selectOriginFilter("web")}>外部发现</button>
          </div>
          {originFilter === "notes" && <label className="field-label compact-field">来源笔记
            <select value={documentFilter} onChange={(event) => setDocumentFilter(event.target.value)}>
              <option value="">所有笔记</option>
              {documents.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}
            </select>
          </label>}
        </div>
        <div className="term-candidate-filters">
          <label className="field-label compact-field">类别<select value={termTypeFilter} onChange={(event) => setTermTypeFilter(event.target.value as TermType | "")}>
            <option value="">全部类别</option><option value="concept">概念</option><option value="entity">命名实体</option><option value="vocabulary">专业词汇</option>
          </select></label>
          <label className="field-label compact-field">匹配<select value={resolutionFilter} onChange={(event) => setResolutionFilter(event.target.value as ResolutionFilter)}>
            <option value="all">已有条目 与 新条目</option><option value="existing">已有条目</option><option value="new">新条目</option>
          </select></label>
        </div>
      </div>
      {notice && <p role="status">{notice}</p>}
      {publishWarnings.length > 0 && <details><summary>查看保存提醒（{publishWarnings.length} 项）</summary><ul>{publishWarnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}

      {!showRejected && <div className="term-candidate-batch surface">
        <span>当前筛选已选 {selectedOpen.length} 项</span>
        <button className="button button-danger" type="button" disabled={batchBusy || !selectedOpen.length} onClick={() => askToDelete(selectedOpen)}>批量暂时移除</button>
        <details className="term-candidate-more-actions">
          <summary className="button button-secondary">更多操作</summary>
          <div><button className="button button-quiet" type="button" disabled={batchBusy || !selectedOpen.length} onClick={() => void rejectSelected()}>批量不再推荐</button><small>拒绝会写入拒绝历史，并影响后续推荐。</small></div>
        </details>
        <small>暂时移除后仍可能再次推荐；不再推荐会记住你的选择。</small>
      </div>}
      {duplicateGroups.length > 0 && <details className="term-candidate-duplicate-groups"><summary>查看 {duplicateGroups.length} 个重复组</summary>{duplicateGroups.map((group) => <section key={group[0].normalized_name}><strong>{group[0].display_name} · {group.length} 项</strong>{group.map((candidate) => <p key={candidate.id}>{candidate.evidence.map((item) => item.origin_title || item.origin_id).join(" · ")}</p>)}<button className="button button-secondary" type="button" disabled={batchBusy} onClick={() => setSelected((current) => Array.from(new Set([...current, ...group.filter((candidate) => candidate.status === "pending").map((candidate) => candidate.id)])))}>选择此组待审项</button></section>)}</details>}

      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading ? <LoadingState /> : visibleCandidates.length ? (
        <div className="term-candidate-list">
          {visibleCandidates.map((candidate) => {
            const suggestedTerm = terms.find((term) => term.id === candidate.suggested_term_id);
            const isExisting = Boolean(candidate.suggested_term_id);
            const canCreateTerm = candidate.evidence.some((item) => !item.origin_rejected);
            const candidateIntent = candidate.discovery_assessment?.why_now.trim()
              || candidate.evidence.find((item) => item.rationale?.trim())?.rationale
              || "等待人工审核的 术语 候选。";
            const evidenceContent = <div className="term-candidate-evidence-list">
              {candidate.evidence.map((item) => (
                <section className={`term-candidate-evidence ${item.origin_rejected ? "rejected" : ""}`} key={item.id}>
                  <div className="term-candidate-evidence-title">
                    {item.origin_type === "document" || item.origin_type === "source" ? (
                      <button type="button" className="term-candidate-origin-link" onClick={() => onOpen(item.origin_type === "document" ? "document" : "source", item.origin_id)}>
                        {item.origin_title || item.origin_id}
                      </button>
                    ) : item.origin_type === "research_work" ? (
                      <button type="button" className="term-candidate-origin-link" onClick={() => navigate(`/research?work_id=${encodeURIComponent(item.origin_id)}`)}>
                        {item.origin_title || item.origin_id}
                      </button>
                    ) : externalEvidenceHref(item.origin_id) ? (
                      <a className="term-candidate-origin-link" href={externalEvidenceHref(item.origin_id)!} target="_blank" rel="noopener noreferrer">
                        {item.origin_title || item.origin_id}
                      </a>
                    ) : <span className="term-candidate-origin-link">{item.origin_title || item.origin_id}</span>}
                    <span>{titleCase(item.origin_type)} · {item.mention}</span>
                    {item.confidence !== null && <span className="term-candidate-confidence">判断把握 {Math.round(item.confidence * 100)}%</span>}
                    {item.origin_rejected && <Chip tone="rose">此来源已拒绝</Chip>}
                  </div>
                  {item.context_excerpt && <blockquote>{item.context_excerpt}</blockquote>}
                  {item.rationale && <p>{item.rationale}</p>}
                  {!item.origin_rejected && candidate.status === "pending" && <button className="text-button term-local-reject" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => rejectTermCandidate(candidate.id, { scope: "local", origin_type: item.origin_type, origin_id: item.origin_id }))}>仅忽略此来源</button>}
                </section>
              ))}
            </div>;
            return (
              <article key={candidate.id} className="term-candidate-card surface">
                <div className="term-candidate-card-topline">
                  {!showRejected && candidate.status === "pending" && <label className="term-candidate-select"><input type="checkbox" aria-label={`选择候选 ${candidate.display_name}`} checked={selected.includes(candidate.id)} disabled={batchBusy} onChange={(event) => setSelected((current) => event.target.checked ? [...current, candidate.id] : current.filter((id) => id !== candidate.id))} />选择</label>}
                  <div className="term-candidate-badges"><Chip>{termTypeLabel(candidate.suggested_type)}</Chip><Chip tone={isExisting ? "green" : "neutral"}>{isExisting ? "已有条目" : "新条目"}</Chip>{candidate.status === "drafting" && <Chip tone="amber">编辑中</Chip>}</div>
                </div>
                <header className="term-candidate-heading">
                  <div>
                    <h2>{candidate.display_name}</h2>
                    {isExisting && <p className="term-candidate-match">匹配到：{suggestedTerm?.title ?? candidate.suggested_term_id}</p>}
                  </div>
                </header>
                <p className="term-candidate-intent">{candidateIntent.length > 180 ? candidateIntent.slice(0, 180) + "…" : candidateIntent}</p>
                <p className="term-candidate-source-summary">来源：{Array.from(new Set(candidate.evidence.map((item) => item.origin_title || item.origin_id))).slice(0, 2).join(" · ") || "暂无来源信息"}</p>
                {actionErrors[candidate.id] && <p className="error-copy" role="alert">{actionErrors[candidate.id]}</p>}
                <footer className="term-candidate-actions">
                  {candidate.status === "rejected" ? <button className="button button-secondary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => restoreTermCandidate(candidate.id))}>恢复</button> : candidate.status === "drafting" ? <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id} onClick={(event) => void openCandidateDraft(candidate, event.currentTarget)}>{busyCandidateId === candidate.id ? "正在打开…" : "继续编辑解释"}</button> : <>
                    {isExisting ? <>
                      <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => acceptTermCandidate(candidate.id, candidate.suggested_term_id!))}>关联已有术语</button>
                      <button className="button button-secondary" type="button" disabled={busyCandidateId === candidate.id} onClick={(event) => openTermPicker(candidate, event.currentTarget)}>选择其他术语</button>
                    </> : <>
                      <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id || !canCreateTerm} title={!canCreateTerm ? "创建 未发布的术语修改 需要至少一个未拒绝的候选来源" : undefined} onClick={(event) => startCreate(candidate, event.currentTarget)}>收录为新术语</button>
                      <button className="button button-secondary" type="button" disabled={busyCandidateId === candidate.id} onClick={(event) => openTermPicker(candidate, event.currentTarget)}>关联已有术语</button>
                    </>}
                    <button className="button button-danger" type="button" disabled={busyCandidateId === candidate.id || batchBusy} onClick={() => void runAction(candidate.id, () => rejectTermCandidate(candidate.id, { scope: "global" }))}>不再推荐</button>
                    <button className="button button-quiet term-candidate-delete" type="button" disabled={busyCandidateId === candidate.id || batchBusy} onClick={() => askToDelete([candidate])}>暂时移除</button>
                  </>}
                </footer>
                {reviewDrafts[candidate.id] && <div className="term-candidate-review-anchor" ref={reviewRefFor(candidate.id)} tabIndex={-1} aria-label={`${candidate.display_name} 的 未发布的术语修改 编辑区`}>
                  <TermCandidateReview candidate={candidate} seed={reviewDrafts[candidate.id]} onClose={() => returnFromReview(candidate.id)} onDone={(warnings = []) => { setNotice("操作已完成。"); setPublishWarnings(warnings); returnFromReview(candidate.id); resource.retry(); }} />
                </div>}
                {candidate.discovery_assessment && <details className="term-candidate-readiness">
                  <summary><Chip tone={candidate.discovery_assessment.recommendation_level === "core_gap" ? "amber" : "neutral"}>{candidate.discovery_assessment.recommendation_level.replaceAll("_", " ")}</Chip> 学习准备情况</summary>
                  <p>{candidate.discovery_assessment.why_now}</p>
                  {(candidate.discovery_assessment.known_prerequisites.length > 0 || candidate.discovery_assessment.missing_prerequisites.length > 0) && <small>已有：{candidate.discovery_assessment.known_prerequisites.join("、") || "—"} · 缺少：{candidate.discovery_assessment.missing_prerequisites.join("、") || "—"}</small>}
                </details>}
                <details className="term-candidate-evidence-disclosure">
                  <summary><strong>来源与证据</strong><span>{candidate.evidence.length} 条 · 展开摘录与分析理由</span></summary>
                  {evidenceContent}
                </details>
              </article>
            );
          })}
        </div>
      ) : <EmptyState title="没有符合条件的候选词" description="分析 正式笔记 后，新发现的词会出现在这里，等待人工确认。" />}

      {pickerCandidate && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyCandidateId) setPickerCandidate(null); }}>
        <section className="explorer-modal term-picker-dialog surface" role="dialog" aria-modal="true" aria-labelledby="term-candidate-picker-title">
          <div className="section-heading"><div><h2 id="term-candidate-picker-title">为“{pickerCandidate.display_name}”选择已有 术语</h2><p>搜索 术语库 后选中一个 术语，建立候选词关系。</p></div><button className="button button-quiet" type="button" disabled={Boolean(busyCandidateId)} onClick={() => setPickerCandidate(null)}>关闭</button></div>
          <label className="field-label">搜索 术语<input ref={pickerSearchRef} value={termQuery} onChange={(event) => setTermQuery(event.target.value)} placeholder="标题、ID 或别名" /></label>
          <div className="term-picker-list" role="listbox" aria-label="术语库 搜索结果">
            {pickerTerms.map((term) => <button type="button" role="option" aria-selected={selectedTermId === term.id} className={selectedTermId === term.id ? "selected" : ""} key={term.id} onClick={() => setSelectedTermId(term.id)}><strong>{term.title}</strong><small>{termTypeLabel(readString(term.metadata.type) || "concept")} · {term.id}</small></button>)}
            {!pickerTerms.length && <p className="subtle-copy">没有找到匹配的 术语。</p>}
          </div>
          {actionErrors[pickerCandidate.id] && <p className="error-copy" role="alert">{actionErrors[pickerCandidate.id]}</p>}
          <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={Boolean(busyCandidateId)} onClick={() => setPickerCandidate(null)}>取消</button><button className="button button-primary" type="button" disabled={!selectedTermId || Boolean(busyCandidateId)} onClick={() => void linkCandidateToSelectedTerm()}>{busyCandidateId === pickerCandidate.id ? "正在保存…" : "链接到所选 术语"}</button></div>
        </section>
      </div>}

      {deleteConfirmation && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !batchBusy) setDeleteConfirmation(null); }}>
        <section className="explorer-modal term-candidate-delete-dialog surface" role="dialog" aria-modal="true" aria-labelledby="term-candidate-delete-title">
          <div className="section-heading"><div><h2 id="term-candidate-delete-title">确认删除候选</h2><p>仅删除当前候选及其证据，不加入拒绝历史；以后仍可能再次被推荐。</p></div></div>
          {deleteConfirmation.length === 1
            ? <strong>{deleteConfirmation[0].display_name}</strong>
            : <div className="term-candidate-delete-list"><strong>将删除 {deleteConfirmation.length} 个已选待审候选：</strong><ul>{deleteConfirmation.map((candidate) => <li key={candidate.id}>{candidate.display_name}</li>)}</ul></div>}
          <div className="term-candidate-dialog-actions">
            <button className="button button-secondary" type="button" disabled={batchBusy} onClick={() => setDeleteConfirmation(null)}>取消</button>
            <button className="button button-danger" type="button" disabled={batchBusy} onClick={() => void confirmDelete()}>{batchBusy ? "正在删除…" : deleteConfirmation.length > 1 ? `删除 ${deleteConfirmation.length} 项` : "删除候选"}</button>
          </div>
        </section>
      </div>}
    </section>
  );
}

function externalEvidenceHref(originId: string): string | null {
  try {
    const url = new URL(originId);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
