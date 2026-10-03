import { useCallback, useEffect, useMemo, useState } from "react";
import {
  dismissResearchCandidate,
  getResearchCandidate,
  getResearchProfile,
  getResearchRun,
  listResearchCandidates,
  listResearchProfiles,
  listResearchRuns,
  shortlistResearchCandidate,
  updateResearchCandidateNote,
  createResearchNote,
  saveResearchSource,
  type CreateResearchNoteInput,
  type ResearchCandidateDetail,
  type ResearchCandidateListItem,
  type ResearchCandidateStatus,
  type ResearchDismissReason,
  type ResearchProfileDetail,
  type ResearchProfileSummary,
  type ResearchRun,
  type ResearchSort,
} from "./api";
import { ResearchCandidateCard, ResearchCandidateDrawer, ResearchCreateNoteDialog, ResearchDismissDialog, ResearchShortlistDialog, type ResearchNoteOptions } from "./ResearchCandidate";
import { ResearchProfilePanel } from "./ResearchProfile";
import { ResearchProfileDefaultsEditor } from "./ResearchProfileDefaultsEditor";
import { ResearchRunDrawer, ResearchRunList } from "./ResearchRun";
import { ErrorState, LoadingState, PageHeader } from "./ui";
import { errorMessage } from "./errors";
import { entityWorkspaceUrl } from "./workspaceRoute";

type ResearchTab = "new" | "shortlisted" | "history" | "runs";
type HistoryStatus = Extract<ResearchCandidateStatus, "dismissed" | "saved_source" | "note_created">;

const HISTORY_STATUSES: Array<{ id: HistoryStatus; label: string }> = [
  { id: "dismissed", label: "Dismissed" },
  { id: "saved_source", label: "Saved Source" },
  { id: "note_created", label: "Note Created" },
];

export default function ResearchPage({ navigate }: { navigate: (path: string) => void }) {
  const [profiles, setProfiles] = useState<ResearchProfileSummary[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [profile, setProfile] = useState<ResearchProfileDetail | null>(null);
  const [pageLoading, setPageLoading] = useState(true);
  const [profileError, setProfileError] = useState("");
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [tab, setTab] = useState<ResearchTab>("new");
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("dismissed");
  const [lensFilter, setLensFilter] = useState("");
  const [sort, setSort] = useState<ResearchSort>("recommended");
  const [items, setItems] = useState<ResearchCandidateListItem[]>([]);
  const [candidateCount, setCandidateCount] = useState(0);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>([]);
  const [dismissTargets, setDismissTargets] = useState<string[] | null>(null);
  const [shortlistTargets, setShortlistTargets] = useState<string[] | null>(null);
  const [createNoteTarget, setCreateNoteTarget] = useState<ResearchCandidateListItem | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [queuedRequestId, setQueuedRequestId] = useState("");
  const [detailId, setDetailId] = useState("");
  const [candidateDetail, setCandidateDetail] = useState<ResearchCandidateDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [runRecords, setRunRecords] = useState<ResearchRun[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runDetail, setRunDetail] = useState<ResearchRun | null>(null);
  const [editingDefaults, setEditingDefaults] = useState(false);
  const [profilePublishWarnings, setProfilePublishWarnings] = useState<string[]>([]);

  const currentSummary = useMemo(() => profiles.find((item) => item.id === selectedProfileId) ?? null, [profiles, selectedProfileId]);

  useEffect(() => {
    let active = true;
    setPageLoading(true);
    setProfileError("");
    void listResearchProfiles().then((result) => {
      if (!active) return;
      setProfiles(result);
      if (!result.some((item) => item.id === selectedProfileId)) setSelectedProfileId(result[0]?.id ?? "");
      if (!result.length) setPageLoading(false);
    }).catch((reason: unknown) => {
      if (active) setProfileError(errorMessage(reason));
    }).finally(() => {
      if (active) setPageLoading(false);
    });
    return () => { active = false; };
  }, [refreshVersion]);

  useEffect(() => {
    if (!selectedProfileId) {
      setProfile(null);
      return;
    }
    let active = true;
    setPageLoading(true);
    setProfileError("");
    void getResearchProfile(selectedProfileId).then((result) => {
      if (active) setProfile(result);
    }).catch((reason: unknown) => {
      if (active) setProfileError(errorMessage(reason));
    }).finally(() => {
      if (active) setPageLoading(false);
    });
    return () => { active = false; };
  }, [selectedProfileId, refreshVersion]);

  const activeStatus: ResearchCandidateStatus | undefined = tab === "new" ? "new" : tab === "shortlisted" ? "shortlisted" : tab === "history" ? historyStatus : undefined;

  useEffect(() => {
    if (!selectedProfileId || tab === "runs" || !profile || profile.profile.id !== selectedProfileId) return;
    let active = true;
    const firstPage = offset === 0;
    setCandidateLoading(true);
    setCandidateError("");
    if (firstPage) setItems([]);
    void listResearchCandidates({
      profile_id: selectedProfileId,
      ...(activeStatus ? { status: activeStatus } : {}),
      ...(lensFilter ? { lens: lensFilter } : {}),
      sort,
      offset,
      limit: 50,
    }).then((result) => {
      if (!active) return;
      setItems((current) => firstPage ? result.candidates : [...current, ...result.candidates]);
      setCandidateCount(result.count);
    }).catch((reason: unknown) => {
      if (active) setCandidateError(errorMessage(reason));
    }).finally(() => {
      if (active) setCandidateLoading(false);
    });
    return () => { active = false; };
  }, [selectedProfileId, tab, activeStatus, historyStatus, lensFilter, sort, offset, refreshVersion, profile]);

  useEffect(() => {
    if (!selectedProfileId || tab !== "runs") return;
    let active = true;
    setRunsLoading(true);
    void listResearchRuns(selectedProfileId, 0, 50).then((result) => {
      if (!active) return;
      setRunRecords(result.runs);
      setRunCount(result.count);
    }).catch((reason: unknown) => {
      if (active) setCandidateError(errorMessage(reason));
    }).finally(() => {
      if (active) setRunsLoading(false);
    });
    return () => { active = false; };
  }, [selectedProfileId, tab, refreshVersion]);

  useEffect(() => {
    if (!detailId) {
      setCandidateDetail(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    void getResearchCandidate(detailId).then((result) => {
      if (active) setCandidateDetail(result);
    }).catch((reason: unknown) => {
      if (active) setActionError(errorMessage(reason));
    }).finally(() => {
      if (active) setDetailLoading(false);
    });
    return () => { active = false; };
  }, [detailId]);

  const refresh = useCallback(() => setRefreshVersion((version) => version + 1), []);

  async function openRun(runId: string) {
    setCandidateError("");
    try {
      setRunDetail(await getResearchRun(runId));
    } catch (reason) {
      setCandidateError(errorMessage(reason));
    }
  }

  function changeTab(next: ResearchTab) {
    setTab(next);
    setOffset(0);
    setItems([]);
    setSelectedCandidates([]);
    setCandidateError("");
  }

  function changeFilter(change: () => void) {
    change();
    setOffset(0);
    setItems([]);
    setSelectedCandidates([]);
  }

  async function shortlist(ids: string[], note: string) {
    setActionBusy(true);
    setActionError("");
    try {
      for (const id of ids) await shortlistResearchCandidate(id, note || undefined);
      setShortlistTargets(null);
      setSelectedCandidates([]);
      refresh();
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function updateCandidateNote(note: string) {
    if (!candidateDetail) return;
    setActionBusy(true);
    setActionError("");
    try {
      const candidate = await updateResearchCandidateNote(candidateDetail.candidate.id, note);
      setCandidateDetail((current) => current ? { ...current, candidate } : current);
      refresh();
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function saveSource(candidateId: string) {
    setActionBusy(true);
    setActionError("");
    try {
      const result = await saveResearchSource(candidateId);
      refresh();
      const query = result.draft_id ? "?edit=1" : "";
      navigate(`/sources/${encodeURIComponent(result.source_id)}${query}`);
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function createNote(candidateId: string, options: ResearchNoteOptions) {
    setActionBusy(true);
    setActionError("");
    try {
      const result = await createResearchNote(candidateId, options satisfies CreateResearchNoteInput);
      setCreateNoteTarget(null);
      refresh();
      const additionalDraftIds = result.source_draft_id ? [result.source_draft_id] : [];
      const hasRelatedDrafts = additionalDraftIds.length > 0 || Boolean(result.collection_draft_id);
      navigate(entityWorkspaceUrl("document", result.document_id, {
        collectionId: result.collection_id ?? undefined,
        edit: true,
        publishAll: hasRelatedDrafts,
        additionalDraftIds,
        researchGroupId: result.group_id,
      }));
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function dismiss(reason: ResearchDismissReason, note: string) {
    const ids = dismissTargets ?? [];
    setActionBusy(true);
    setActionError("");
    try {
      for (const id of ids) await dismissResearchCandidate(id, reason, note);
      setDismissTargets(null);
      setSelectedCandidates([]);
      refresh();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setActionBusy(false);
    }
  }

  function toggleSelected(id: string, checked: boolean) {
    setSelectedCandidates((current) => checked ? [...new Set([...current, id])] : current.filter((item) => item !== id));
  }

  const tabs: Array<{ id: ResearchTab; label: string; count?: number }> = [
    { id: "new", label: "New", count: currentSummary?.inbox.new_count },
    { id: "shortlisted", label: "Shortlist" },
    { id: "history", label: "History" },
    { id: "runs", label: "Runs" },
  ];

  if (pageLoading && !profiles.length) return <LoadingState label="正在读取 Research Profiles…" />;
  if (profileError && !profiles.length) return <ErrorState message={profileError} retry={refresh} />;
  if (!profiles.length) return <div className="page-stack"><PageHeader eyebrow="DISCOVERY WORKSPACE" title="Research" description="从外部研究发现候选内容，并由你决定哪些进入知识库。" /><div className="surface"><div className="empty-state"><span className="empty-mark">⌕</span><strong>没有可用的 Research Profile</strong><p>添加并验证 Profile 配置后，这里会显示研究发现。</p></div></div></div>;

  return <div className="page-stack research-page">
    <PageHeader eyebrow="DISCOVERY WORKSPACE" title="Research" description="外部发现、知识关联与候选处理。每条发现都保留来源和分析依据。" action={<label className="research-profile-select"><span>Profile</span><select aria-label="Research Profile" value={selectedProfileId} onChange={(event) => { setEditingDefaults(false); setSelectedProfileId(event.target.value); setTab("new"); setOffset(0); setSelectedCandidates([]); }}><option value="" disabled>Select a Profile</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>} />
    {profileError && <ErrorState message={profileError} retry={refresh} />}
    {profile && profile.profile.id === selectedProfileId && currentSummary && <ResearchProfilePanel summary={currentSummary} detail={profile} onRefresh={refresh} onQueued={(id) => { setQueuedRequestId(id); setTab("new"); }} onEditDefaults={() => setEditingDefaults(true)} />}
    {profilePublishWarnings.length > 0 && <div className="notice research-queued-notice" role="status"><strong>Profile published with warnings</strong><ul>{profilePublishWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><button className="text-button" onClick={() => setProfilePublishWarnings([])}>Dismiss</button></div>}
    {editingDefaults && profile?.profile.id === selectedProfileId && <ResearchProfileDefaultsEditor profile={profile.profile} canonicalContent={profile.canonical_content} onClose={() => setEditingDefaults(false)} onPublished={(warnings) => { setEditingDefaults(false); setProfilePublishWarnings(warnings); refresh(); }} />}
    {queuedRequestId && <div className="notice research-queued-notice" role="status"><strong>Search queued</strong><span>Request {queuedRequestId.slice(0, 10)} 已加入本地队列；将在下次 Research tick 执行。</span><button className="text-button" onClick={() => setQueuedRequestId("")}>Dismiss</button></div>}

    <section className="surface research-inbox-section">
      <div className="research-inbox-heading"><div><p className="eyebrow">RESEARCH INBOX</p><h2>Discoveries</h2><p>先看清它是什么、为什么推荐，以及它和现有知识的关系。</p></div><div className="research-tab-list" role="tablist" aria-label="Research sections">{tabs.map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? "active" : ""} onClick={() => changeTab(item.id)}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</div></div>
      {tab !== "runs" && <>
        <div className="research-filter-bar">
          {tab === "history" && <label className="field-label">History<select value={historyStatus} onChange={(event) => changeFilter(() => setHistoryStatus(event.target.value as HistoryStatus))}>{HISTORY_STATUSES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
          <label className="field-label">Lens<select value={lensFilter} onChange={(event) => changeFilter(() => setLensFilter(event.target.value))}><option value="">All Lenses</option>{profile?.profile.id === selectedProfileId && profile.profile.lenses.map((lens) => <option key={lens.id} value={lens.id}>{lens.title}</option>)}</select></label>
          <label className="field-label">Sort<select value={sort} onChange={(event) => changeFilter(() => setSort(event.target.value as ResearchSort))}><option value="recommended">Recommended</option><option value="newest">Newest</option><option value="most_relevant">Most relevant</option><option value="most_novel">Most novel to library</option></select></label>
          <span className="research-result-count">{candidateCount} {tab === "new" ? "new candidates" : tab === "shortlisted" ? "shortlisted" : "in history"}</span>
        </div>
        {tab !== "history" && (tab === "new" || tab === "shortlisted") && items.length > 0 && <div className="research-batch-toolbar"><label><input type="checkbox" checked={items.length > 0 && items.every((item) => selectedCandidates.includes(item.candidate.id))} onChange={(event) => setSelectedCandidates(event.target.checked ? items.map((item) => item.candidate.id) : [])} /> Select visible</label><span>{selectedCandidates.length} selected</span><div>{selectedCandidates.length > 0 && <>{tab === "new" && <button className="button button-secondary" disabled={actionBusy} onClick={() => setShortlistTargets(selectedCandidates)}>Shortlist selected</button>}<button className="button button-quiet" disabled={actionBusy} onClick={() => setDismissTargets(selectedCandidates)}>Dismiss selected</button></>}</div></div>}
        {actionError && <p className="error-copy research-inline-error" role="alert">{actionError}</p>}
        {candidateError && <ErrorState message={candidateError} retry={refresh} />}
        {candidateLoading && items.length === 0 ? <LoadingState label="正在读取候选内容…" /> : items.length && profile?.profile.id === selectedProfileId ? <div className="research-candidate-list">{items.map((item) => <ResearchCandidateCard key={item.candidate.id} item={item} profile={profile.profile} selected={selectedCandidates.includes(item.candidate.id)} selectable={tab === "new" || tab === "shortlisted"} busy={actionBusy} onSelect={(checked) => toggleSelected(item.candidate.id, checked)} onDetails={() => { setActionError(""); setDetailId(item.candidate.id); }} onShortlist={() => setShortlistTargets([item.candidate.id])} onDismiss={() => setDismissTargets([item.candidate.id])} onSaveSource={() => void saveSource(item.candidate.id)} onCreateNote={() => { setActionError(""); setCreateNoteTarget(item); }} />)}</div> : !candidateError && !items.length && <div className="empty-state"><span className="empty-mark">⌕</span><strong>{tab === "new" ? "No new candidates" : tab === "shortlisted" ? "No shortlisted candidates" : `No ${HISTORY_STATUSES.find((item) => item.id === historyStatus)?.label.toLowerCase()} items`}</strong><p>{tab === "new" ? "Run Search Now or wait for the scheduled discovery. Inbox capacity pauses discovery when full." : tab === "shortlisted" ? "Shortlisted papers will stay here while you review them." : "Processed candidates are kept in History for reference."}</p></div>}
        {items.length > 0 && items.length < candidateCount && <div className="research-load-more"><button className="button button-secondary" disabled={candidateLoading} onClick={() => setOffset(items.length)}>{candidateLoading ? "Loading…" : "Load more"}</button></div>}
      </>}
      {tab === "runs" && <>
        {candidateError && <ErrorState message={candidateError} retry={refresh} />}
        <ResearchRunList runs={runRecords} count={runCount} loading={runsLoading} onOpen={(runId) => void openRun(runId)} />
      </>}
    </section>

    {detailId && (detailLoading ? <div className="research-drawer-overlay"><aside className="research-drawer" role="dialog" aria-modal="true"><LoadingState label="正在载入 Candidate provenance…" /><button className="button button-secondary" onClick={() => setDetailId("")}>Close</button></aside></div> : candidateDetail && profile && <ResearchCandidateDrawer detail={candidateDetail} profile={profile.profile} noteBusy={actionBusy} noteError={actionError} onSaveNote={(note) => void updateCandidateNote(note)} onClose={() => { setDetailId(""); setCandidateDetail(null); }} onOpenEntity={(path) => { setDetailId(""); navigate(path); }} />)}
    {runDetail && <ResearchRunDrawer run={runDetail} onClose={() => setRunDetail(null)} />}
    {dismissTargets && <ResearchDismissDialog count={dismissTargets.length} busy={actionBusy} onClose={() => setDismissTargets(null)} onSubmit={(reason, note) => void dismiss(reason, note)} />}
    {shortlistTargets && <ResearchShortlistDialog count={shortlistTargets.length} busy={actionBusy} error={actionError} onClose={() => setShortlistTargets(null)} onSubmit={(note) => void shortlist(shortlistTargets, note)} />}
    {createNoteTarget && <ResearchCreateNoteDialog title={createNoteTarget.work.title} busy={actionBusy} onClose={() => setCreateNoteTarget(null)} onCreate={(options) => void createNote(createNoteTarget.candidate.id, options)} />}
  </div>;
}
