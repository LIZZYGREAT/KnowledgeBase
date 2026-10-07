import { useMemo, useState } from "react";
import {
  acceptTermCandidate,
  createCandidateTermDraft,
  getDraft,
  listTermCandidates,
  rejectTermCandidate,
  requestCandidateTermDraftProposal,
  type EntitySummary,
  type TermCandidate,
  type TermType,
} from "../api";
import { errorMessage } from "../errors";
import { Chip, EmptyState, ErrorState, LoadingState, titleCase } from "../ui";
import { readList, readString, useResource, type Navigate, type SelectEntity } from "./PageShared";

type OriginFilter = "all" | "notes";
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
  const [resolutionFilter, setResolutionFilter] = useState<ResolutionFilter>("all");
  const [busyCandidateId, setBusyCandidateId] = useState("");
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [createCandidate, setCreateCandidate] = useState<TermCandidate | null>(null);
  const [createConsent, setCreateConsent] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createdDraftId, setCreatedDraftId] = useState("");
  const [pickerCandidate, setPickerCandidate] = useState<TermCandidate | null>(null);
  const [selectedTermId, setSelectedTermId] = useState("");
  const [termQuery, setTermQuery] = useState("");

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
    if (candidate.status !== "pending" && candidate.status !== "drafting") return false;
    if (originFilter === "notes" && !candidate.evidence.some((item) => item.origin_type === "document")) return false;
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

  function openTermPicker(candidate: TermCandidate) {
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

  async function createAndGenerateTermDraft() {
    if (!createCandidate || !createConsent || createBusy) return;
    setCreateBusy(true);
    setCreateError("");
    try {
      const result = await createCandidateTermDraft(createCandidate.id);
      setCreatedDraftId(result.draft.id);
      resource.retry();
      await requestCandidateTermDraftProposal(result.draft.id, createCandidate.id);
      setCreateCandidate(null);
      setCreateConsent(false);
      onOpen("term", result.draft.entity_id);
    } catch (reason) {
      setCreateError(errorMessage(reason));
      resource.retry();
    } finally {
      setCreateBusy(false);
    }
  }

  async function openCandidateDraft(candidate: TermCandidate) {
    if (!candidate.draft_id) return;
    setBusyCandidateId(candidate.id);
    setActionErrors((current) => ({ ...current, [candidate.id]: "" }));
    try {
      const draft = await getDraft(candidate.draft_id);
      onOpen("term", draft.entity_id);
    } catch (reason) {
      setActionErrors((current) => ({ ...current, [candidate.id]: errorMessage(reason) }));
      resource.retry();
    } finally {
      setBusyCandidateId("");
    }
  }

  function startCreate(candidate: TermCandidate) {
    setCreateCandidate(candidate);
    setCreateConsent(false);
    setCreateError("");
    setCreatedDraftId("");
  }

  return (
    <section className="term-candidates-panel" aria-label="Term Candidates">
      <div className="term-candidate-toolbar surface">
        <div className="term-candidate-origin-filter">
          <div className="segmented-control" role="group" aria-label="候选来源">
            <button type="button" aria-pressed={originFilter === "all"} className={originFilter === "all" ? "active" : ""} onClick={() => { setOriginFilter("all"); setDocumentFilter(""); }}>All</button>
            <button type="button" aria-pressed={originFilter === "notes"} className={originFilter === "notes" ? "active" : ""} onClick={() => setOriginFilter("notes")}>Notes</button>
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
            <option value="">全部类别</option><option value="concept">Concept</option><option value="entity">Entity</option><option value="vocabulary">Vocabulary</option>
          </select></label>
          <label className="field-label compact-field">匹配<select value={resolutionFilter} onChange={(event) => setResolutionFilter(event.target.value as ResolutionFilter)}>
            <option value="all">Existing 与 New</option><option value="existing">Existing</option><option value="new">New</option>
          </select></label>
        </div>
        <span className="count-label">{visibleCandidates.length} 个待审核</span>
      </div>

      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading ? <LoadingState /> : visibleCandidates.length ? (
        <div className="term-candidate-list">
          {visibleCandidates.map((candidate) => {
            const suggestedTerm = terms.find((term) => term.id === candidate.suggested_term_id);
            const isExisting = Boolean(candidate.suggested_term_id);
            const canCreateTerm = candidate.evidence.some((item) => !item.origin_rejected);
            return (
              <article key={candidate.id} className="term-candidate-card surface">
                <header className="term-candidate-heading">
                  <div>
                    <div className="term-candidate-badges"><Chip>{titleCase(candidate.suggested_type)}</Chip><Chip tone={isExisting ? "green" : "neutral"}>{isExisting ? "Existing" : "New"}</Chip>{candidate.status === "drafting" && <Chip tone="amber">Drafting</Chip>}</div>
                    <h2>{candidate.display_name}</h2>
                    {isExisting && <p className="term-candidate-match">匹配到：{suggestedTerm?.title ?? candidate.suggested_term_id}</p>}
                  </div>
                  <span className="term-candidate-id">{candidate.normalized_name}</span>
                </header>

                {candidate.discovery_assessment && <section className="term-candidate-readiness" aria-label="Readiness explanation">
                  <div><Chip tone={candidate.discovery_assessment.recommendation_level === "core_gap" ? "amber" : "neutral"}>{candidate.discovery_assessment.recommendation_level.replaceAll("_", " ")}</Chip><Chip>{candidate.discovery_assessment.readiness} readiness</Chip></div>
                  <p>{candidate.discovery_assessment.why_now}</p>
                  {(candidate.discovery_assessment.known_prerequisites.length > 0 || candidate.discovery_assessment.missing_prerequisites.length > 0) && <small>已有：{candidate.discovery_assessment.known_prerequisites.join("、") || "—"} · 缺少：{candidate.discovery_assessment.missing_prerequisites.join("、") || "—"}</small>}
                </section>}

                <div className="term-candidate-evidence-list">
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
                      {!item.origin_rejected && candidate.status === "pending" && <button className="text-button term-local-reject" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => rejectTermCandidate(candidate.id, { scope: "local", origin_type: item.origin_type, origin_id: item.origin_id }))}>仅此来源不再推荐</button>}
                    </section>
                  ))}
                </div>

                {actionErrors[candidate.id] && <p className="error-copy" role="alert">{actionErrors[candidate.id]}</p>}
                <footer className="term-candidate-actions">
                  {candidate.status === "drafting" ? <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void openCandidateDraft(candidate)}>{busyCandidateId === candidate.id ? "正在打开…" : "打开 Term Draft"}</button> : <>
                    {isExisting ? <>
                      <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => acceptTermCandidate(candidate.id, candidate.suggested_term_id!))}>Accept Relation</button>
                      <button className="button button-secondary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => openTermPicker(candidate)}>Choose Another Existing…</button>
                    </> : <>
                      <button className="button button-primary" type="button" disabled={busyCandidateId === candidate.id || !canCreateTerm} title={!canCreateTerm ? "创建 Term Draft 需要至少一个未拒绝的候选来源" : undefined} onClick={() => startCreate(candidate)}>Create Term</button>
                      <button className="button button-secondary" type="button" disabled={busyCandidateId === candidate.id} onClick={() => openTermPicker(candidate)}>Link Existing…</button>
                    </>}
                    <button className="button button-danger term-global-reject" type="button" disabled={busyCandidateId === candidate.id} onClick={() => void runAction(candidate.id, () => rejectTermCandidate(candidate.id, { scope: "global" }))}>全局不再推荐</button>
                  </>}
                </footer>
              </article>
            );
          })}
        </div>
      ) : <EmptyState title="没有符合条件的候选词" description="分析 Canonical Note 后，新发现的词会出现在这里，等待人工确认。" />}

      {createCandidate && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !createBusy) setCreateCandidate(null); }}>
        <section className="explorer-modal term-candidate-dialog surface" role="dialog" aria-modal="true" aria-labelledby="create-term-candidate-title">
          <div className="section-heading"><div><h2 id="create-term-candidate-title">创建 Term Draft</h2><p>先生成本地 Draft，再让 AI 根据候选来源的摘录和分析理由给出可审核的定义建议。</p></div><button className="text-button" type="button" disabled={createBusy} onClick={() => setCreateCandidate(null)}>关闭</button></div>
          <div className="term-candidate-dialog-context">
            <strong>{createCandidate.display_name} · {titleCase(createCandidate.suggested_type)}</strong>
            {createCandidate.evidence.filter((item) => !item.origin_rejected).slice(0, 5).map((item) => <blockquote key={item.id}><span>{titleCase(item.origin_type)} · {item.origin_title || item.origin_id}</span>{item.context_excerpt && <span>{item.context_excerpt}</span>}{item.rationale && <span>{item.rationale}</span>}</blockquote>)}
            <p>将发送 Term Registry、候选词类型，以及最多 5 条候选来源的标题或标识、摘录和分析理由。不会发送整份文档或网页。</p>
          </div>
          <label className="ai-consent term-candidate-consent"><input type="checkbox" checked={createConsent} onChange={(event) => setCreateConsent(event.target.checked)} /><span>我同意将上述信息发送给 DeepSeek，用于生成 Term Draft 建议。</span></label>
          {createError && <p className="error-copy" role="alert">{createdDraftId ? `Term Draft 已创建；AI 建议未完成。${createError}` : createError}</p>}
          {createdDraftId && <button type="button" className="text-button" disabled={createBusy} onClick={() => void openCandidateDraft({ ...createCandidate, draft_id: createdDraftId, status: "drafting" })}>打开已创建的 Term Draft</button>}
          <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={createBusy} onClick={() => setCreateCandidate(null)}>取消</button><button className="button button-primary" type="button" disabled={!createConsent || createBusy} onClick={() => void createAndGenerateTermDraft()}>{createBusy ? "正在生成…" : createdDraftId ? "重试 AI 建议并打开" : "同意并生成建议"}</button></div>
        </section>
      </div>}

      {pickerCandidate && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyCandidateId) setPickerCandidate(null); }}>
        <section className="explorer-modal term-picker-dialog surface" role="dialog" aria-modal="true" aria-labelledby="term-candidate-picker-title">
          <div className="section-heading"><div><h2 id="term-candidate-picker-title">选择已有 Term</h2><p>搜索 Registry 后选中一个 Term，建立候选词关系。</p></div><button className="text-button" type="button" disabled={Boolean(busyCandidateId)} onClick={() => setPickerCandidate(null)}>关闭</button></div>
          <label className="field-label">搜索 Term<input value={termQuery} onChange={(event) => setTermQuery(event.target.value)} placeholder="标题、ID 或别名" autoFocus /></label>
          <div className="term-picker-list" role="listbox" aria-label="Term Registry 搜索结果">
            {pickerTerms.map((term) => <button type="button" role="option" aria-selected={selectedTermId === term.id} className={selectedTermId === term.id ? "selected" : ""} key={term.id} onClick={() => setSelectedTermId(term.id)}><strong>{term.title}</strong><small>{titleCase(readString(term.metadata.type) || "concept")} · {term.id}</small></button>)}
            {!pickerTerms.length && <p className="subtle-copy">没有找到匹配的 Term。</p>}
          </div>
          {actionErrors[pickerCandidate.id] && <p className="error-copy" role="alert">{actionErrors[pickerCandidate.id]}</p>}
          <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={Boolean(busyCandidateId)} onClick={() => setPickerCandidate(null)}>取消</button><button className="button button-primary" type="button" disabled={!selectedTermId || Boolean(busyCandidateId)} onClick={() => void linkCandidateToSelectedTerm()}>{busyCandidateId === pickerCandidate.id ? "正在保存…" : "链接到所选 Term"}</button></div>
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
