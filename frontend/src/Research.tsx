import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { parse } from "yaml";
import {
  dismissResearchCandidate,
  restoreResearchCandidate,
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
  getDraft,
  preflightDraft,
  publishDraft,
  type CreateResearchNoteInput,
  type ResearchCandidateDetail,
  type ResearchCandidateListItem,
  type ResearchCandidateStatus,
  type ResearchDismissReason,
  type ResearchProfileDetail,
  type ResearchProfile,
  type ResearchProfileSummary,
  type ResearchRun,
  type ResearchSort,
  type Draft,
} from "./api";
import { ResearchCandidateCard, ResearchCandidateDrawer, ResearchCreateNoteDialog, ResearchDismissDialog, ResearchShortlistDialog, type ResearchNoteOptions } from "./ResearchCandidate";
import { ResearchProfilePanel } from "./ResearchProfile";
import { ResearchProfileDefaultsEditor } from "./ResearchProfileDefaultsEditor";
import { ResearchProfileCreateDialog } from "./ResearchProfileCreateDialog";
import { ResearchSourceReview } from "./ResearchSourceReview";
import { ResearchRunDrawer, ResearchRunList } from "./ResearchRun";
import { ErrorState, LoadingState, PageHeader } from "./ui";
import { errorMessage } from "./errors";
import { entityWorkspaceUrl } from "./workspaceRoute";
import type { ResearchLanguage } from "./ResearchLanguage";

type ResearchTab = "new" | "shortlisted" | "history" | "runs";
type HistoryStatus = Extract<ResearchCandidateStatus, "dismissed" | "saved_source" | "note_created">;

const HISTORY_STATUSES: Array<{ id: HistoryStatus; label: string }> = [
  { id: "dismissed", label: "已忽略" },
  { id: "saved_source", label: "已收藏文献" },
  { id: "note_created", label: "已创建笔记" },
];

export default function ResearchPage({ navigate }: { navigate: (path: string) => void }) {
  const [requestedWorkId] = useState(() => new URLSearchParams(window.location.search).get("work_id") ?? "");
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
  const [sourceReview, setSourceReview] = useState<Draft | null>(null);
  const [searchQueued, setSearchQueued] = useState(false);
  const [restoreNotice, setRestoreNotice] = useState(false);
  const [detailId, setDetailId] = useState("");
  const [detailLanguage, setDetailLanguage] = useState<ResearchLanguage>("en");
  const detailLanguageUpdater = useRef<(language: ResearchLanguage) => void>(() => undefined);
  const [candidateDetail, setCandidateDetail] = useState<ResearchCandidateDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [runRecords, setRunRecords] = useState<ResearchRun[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runDetail, setRunDetail] = useState<ResearchRun | null>(null);
  const [profileEditor, setProfileEditor] = useState<{ profile: ResearchProfile; canonicalContent: string; draftCreatedInThisFlow: boolean } | null>(null);
  const [createProfileSource, setCreateProfileSource] = useState<ResearchProfile | null | undefined>(undefined);
  const [profilePublishWarnings, setProfilePublishWarnings] = useState<string[]>([]);
  const [manualHistoryRange, setManualHistoryRange] = useState<{ start: string; end: string } | null>(null);

  const currentSummary = useMemo(() => profiles.find((item) => item.id === selectedProfileId) ?? null, [profiles, selectedProfileId]);

  useEffect(() => {
    let active = true;
    setPageLoading(true);
    setProfileError("");
    void listResearchProfiles().then((result) => {
      if (!active) return;
      setProfiles(result);
      if (!requestedWorkId && !result.some((item) => item.id === selectedProfileId)) setSelectedProfileId(result[0]?.id ?? "");
      if (!result.length) setPageLoading(false);
    }).catch((reason: unknown) => {
      if (active) setProfileError(errorMessage(reason));
    }).finally(() => {
      if (active) setPageLoading(false);
    });
    return () => { active = false; };
  }, [refreshVersion, requestedWorkId]);

  useEffect(() => {
    if (!requestedWorkId) return;
    let active = true;
    setCandidateError("");
    void listResearchCandidates({ work_id: requestedWorkId, sort: "newest", limit: 1 })
      .then((result) => {
        if (!active) return;
        const item = result.candidates[0];
        if (!item) {
          setCandidateError("没有找到与此论文推荐 Work 对应的 Candidate。");
          return;
        }
        const status = item.candidate.status;
        if (status === "dismissed" || status === "saved_source" || status === "note_created") {
          setTab("history");
          setHistoryStatus(status);
        } else {
          setTab(status);
        }
        setSelectedProfileId(item.candidate.profile_id);
        setOffset(0);
        setSelectedCandidates([]);
        setDetailId(item.candidate.id);
        setCandidateDetail(null);
      })
      .catch((reason: unknown) => {
        if (active) setCandidateError(errorMessage(reason));
      });
    return () => { active = false; };
  }, [requestedWorkId]);

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
    if (candidateDetail?.candidate.id === detailId) return;
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
  }, [candidateDetail?.candidate.id, detailId]);

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
    if (next === "new") setRestoreNotice(false);
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

  async function shortlist(ids: string[], note = "") {
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
      setDetailId("");
      setCandidateDetail(null);
      refresh();
      const query = result.draft_id ? "?edit=1" : "";
      navigate(`/sources/${encodeURIComponent(result.source_id)}${query}`);
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function approveSource(candidateId: string) {
    const result = await saveResearchSource(candidateId);
    if (result.draft_id) {
      const draft = await getDraft(result.draft_id);
      if (result.action === "draft_reused") {
        setActionError("");
        setSourceReview(draft);
        return;
      }
      try {
        const preflight = await preflightDraft(draft.id);
        if (!preflight.valid || preflight.conflict) throw new Error(preflight.errors.join("；") || "文献发布校验失败，修改已保留。");
        await publishDraft(draft.id, draft.revision);
      } catch (reason) {
        setSourceReview(draft);
        setActionError(errorMessage(reason));
        throw reason;
      }
    }
    refresh();
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

  async function beginCreateNote(item: ResearchCandidateListItem) {
    setActionBusy(true);
    setActionError("");
    try {
      const detail = await getResearchCandidate(item.candidate.id);
      if (detail.conversion_blocker === "ambiguous_source") {
        setCreateNoteTarget(null);
        setCandidateDetail(detail);
        setDetailId(item.candidate.id);
        setDetailLoading(false);
        return;
      }
      setCreateNoteTarget(item);
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function dismiss(ids: string[], reason?: ResearchDismissReason, note = "") {
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

  async function restoreCandidate(candidateId: string) {
    setActionBusy(true);
    setActionError("");
    setRestoreNotice(false);
    try {
      await restoreResearchCandidate(candidateId);
      setSelectedCandidates([]);
      setRestoreNotice(true);
      refresh();
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  function toggleSelected(id: string, checked: boolean) {
    setSelectedCandidates((current) => checked ? [...new Set([...current, id])] : current.filter((item) => item !== id));
  }

  const tabs: Array<{ id: ResearchTab; label: string; count?: number }> = [
    { id: "new", label: "待看", count: currentSummary?.inbox.new_count },
    { id: "shortlisted", label: "稍后阅读" },
    { id: "history", label: "处理记录" },
    { id: "runs", label: "检索记录" },
  ];

  const profileLayers = <>
    {createProfileSource !== undefined && <ResearchProfileCreateDialog
      profiles={profiles}
      sourceProfile={createProfileSource}
      onClose={() => setCreateProfileSource(undefined)}
      onCreated={(createdProfile, draftContent, draftCreatedInThisFlow) => {
        const savedProfile = parse(draftContent) as ResearchProfile;
        setCreateProfileSource(undefined);
        setProfileEditor({ profile: savedProfile ?? createdProfile, canonicalContent: "", draftCreatedInThisFlow });
      }}
    />}
    {profileEditor && <ResearchProfileDefaultsEditor
      profile={profileEditor.profile}
      canonicalContent={profileEditor.canonicalContent}
      draftCreatedInThisFlow={profileEditor.draftCreatedInThisFlow}
      previousHistoryAnchorYear={profile?.profile.id === profileEditor.profile.id ? profile.history_anchor_year : null}
      onClose={() => setProfileEditor(null)}
      onPublished={(warnings, backfillRange) => {
        const publishedProfileId = profileEditor.profile.id;
        setProfileEditor(null);
        if (!profileEditor.canonicalContent) setSelectedProfileId(publishedProfileId);
        setProfilePublishWarnings(warnings);
        setManualHistoryRange(backfillRange ?? null);
        refresh();
      }}
    />}
  </>;

  if (pageLoading && !profiles.length) return <LoadingState label="正在读取研究方向…" />;
  if (profileError && !profiles.length) return <ErrorState message={profileError} retry={refresh} />;
  if (!profiles.length) return <div className="page-stack"><PageHeader eyebrow="发现与筛选论文" title="论文推荐" description="从外部研究发现候选内容，并由你决定哪些进入知识库。" action={<button className="button button-primary" onClick={() => setCreateProfileSource(null)}>新建研究方向</button>} /><div className="surface"><div className="empty-state"><span className="empty-mark">⌕</span><strong>没有可用的研究方向</strong><p>添加并验证研究方向配置后，这里会显示研究发现。</p></div></div>{profileLayers}</div>;

  return <div className="page-stack research-page">
    <PageHeader eyebrow="发现与筛选论文" title="论文推荐" description="外部发现、知识关联与候选处理。每条发现都保留来源和分析依据。" action={<div className="research-profile-header-actions"><label className="research-profile-select"><span>研究方向</span><select aria-label="研究方向" value={selectedProfileId} onChange={(event) => { setProfileEditor(null); setSelectedProfileId(event.target.value); setTab("new"); setRestoreNotice(false); setOffset(0); setSelectedCandidates([]); }}><option value="" disabled>选择研究方向</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button className="button button-secondary" onClick={() => setCreateProfileSource(null)}>新建研究方向</button><button className="button button-quiet" disabled={!profile || profile.profile.id !== selectedProfileId} onClick={() => setCreateProfileSource(profile?.profile ?? null)}>复制研究方向</button></div>} />
    {profileError && <ErrorState message={profileError} retry={refresh} />}
    {profile && profile.profile.id === selectedProfileId && currentSummary && <ResearchProfilePanel summary={currentSummary} detail={profile} initialManualHistoryRange={manualHistoryRange} onManualHistoryRangeOpened={() => setManualHistoryRange(null)} onRefresh={refresh} onResults={() => { setTab("new"); refresh(); }} onRun={(id) => { void getResearchRun(id).then(setRunDetail).catch((reason) => setActionError(errorMessage(reason))); }} onQueued={() => { setSearchQueued(true); setTab("new"); refresh(); }} onEditDefaults={() => setProfileEditor({ profile: profile.profile, canonicalContent: profile.canonical_content, draftCreatedInThisFlow: false })} />}
    {profilePublishWarnings.length > 0 && <div className="notice research-queued-notice" role="status"><strong>研究方向已保存，并有格式提醒</strong><ul>{profilePublishWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><button className="text-button" onClick={() => setProfilePublishWarnings([])}>忽略</button></div>}
    {searchQueued && <div className="notice research-queued-notice" role="status"><strong>检索请求已提交。</strong><span>可在研究方向中查看真实执行状态。</span><button className="text-button" onClick={() => setSearchQueued(false)}>关闭提示</button></div>}
    {restoreNotice && <div className="notice research-queued-notice" role="status"><strong>已恢复到待看论文。</strong><button className="button button-secondary" onClick={() => changeTab("new")}>查看待看论文</button></div>}

    <section className="surface research-inbox-section">
      <div className="research-inbox-heading"><div><p className="eyebrow">待看论文</p><h2>论文发现</h2><p>先看清它是什么、为什么推荐，以及它和现有知识的关系。</p></div><div className="research-tab-list" role="tablist" aria-label="论文推荐分类">{tabs.map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? "active" : ""} onClick={() => changeTab(item.id)}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</div></div>
      {tab !== "runs" && <>
        <div className="research-filter-bar">
          {tab === "history" && <label className="field-label">处理记录<select value={historyStatus} onChange={(event) => changeFilter(() => setHistoryStatus(event.target.value as HistoryStatus))}>{HISTORY_STATUSES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
          <label className="field-label">检索主题<select value={lensFilter} onChange={(event) => changeFilter(() => setLensFilter(event.target.value))}><option value="">所有检索主题</option>{profile?.profile.id === selectedProfileId && profile.profile.lenses.map((lens) => <option key={lens.id} value={lens.id}>{lens.title}</option>)}</select></label>
          <label className="field-label">排序<select value={sort} onChange={(event) => changeFilter(() => setSort(event.target.value as ResearchSort))}><option value="recommended">推荐顺序</option><option value="newest">最新</option><option value="most_relevant">相关性最高</option><option value="most_novel">新颖性最高</option></select></label>
          <span className="research-result-count">{candidateCount} {tab === "new" ? "篇待看论文" : tab === "shortlisted" ? "篇稍后阅读" : "条处理记录"}</span>
        </div>
        {tab !== "history" && (tab === "new" || tab === "shortlisted") && items.length > 0 && <div className="research-batch-toolbar"><label><input type="checkbox" checked={items.length > 0 && items.every((item) => selectedCandidates.includes(item.candidate.id))} onChange={(event) => setSelectedCandidates(event.target.checked ? items.map((item) => item.candidate.id) : [])} /> 选择当前显示的论文</label><span>已选 {selectedCandidates.length} 项</span><div>{selectedCandidates.length > 0 && <>{tab === "new" && <button className="button button-secondary" disabled={actionBusy} onClick={() => setShortlistTargets(selectedCandidates)}>稍后阅读所选论文</button>}<button className="button button-quiet" disabled={actionBusy} onClick={() => setDismissTargets(selectedCandidates)}>忽略所选论文</button></>}</div></div>}
        {actionError && <p className="error-copy research-inline-error" role="alert">{actionError}</p>}
        {candidateError && <ErrorState message={candidateError} retry={refresh} />}
        {candidateLoading && items.length === 0 ? <LoadingState label="正在读取候选内容…" /> : items.length && profile?.profile.id === selectedProfileId ? <div className="research-candidate-list">{items.map((item) => <ResearchCandidateCard key={item.candidate.id} item={item} profile={profile.profile} selected={selectedCandidates.includes(item.candidate.id)} selectable={tab === "new" || tab === "shortlisted"} busy={actionBusy} onSelect={(checked) => toggleSelected(item.candidate.id, checked)} onDetails={(language, onLanguageChange) => { setActionError(""); setDetailLanguage(language); detailLanguageUpdater.current = onLanguageChange; setDetailId(item.candidate.id); }} onShortlist={() => void shortlist([item.candidate.id])} onDismiss={() => void dismiss([item.candidate.id])} onRestore={() => void restoreCandidate(item.candidate.id)} onCreateNote={() => void beginCreateNote(item)} onReviewTerms={() => navigate("/terms?tab=candidates")} onApprove={() => approveSource(item.candidate.id)} onOpenEntity={navigate} />)}</div> : !candidateError && !items.length && <div className="empty-state"><span className="empty-mark">⌕</span><strong>{tab === "new" ? "暂无新推荐" : tab === "shortlisted" ? "暂无稍后阅读的论文" : `暂无${HISTORY_STATUSES.find((item) => item.id === historyStatus)?.label}记录`}</strong><p>{tab === "new" ? "点击立即检索查找论文；自动发现需启用定时任务。待看论文满额时，先处理已有推荐。" : tab === "shortlisted" ? "稍后阅读的论文保留在这里，方便继续处理。" : "处理过的论文保留在记录中，方便查询。"}</p></div>}
        {items.length > 0 && items.length < candidateCount && <div className="research-load-more"><button className="button button-secondary" disabled={candidateLoading} onClick={() => setOffset(items.length)}>{candidateLoading ? "正在读取…" : "加载更多"}</button></div>}
      </>}
      {tab === "runs" && <>
        {candidateError && <ErrorState message={candidateError} retry={refresh} />}
        <ResearchRunList runs={runRecords} count={runCount} loading={runsLoading} onOpen={(runId) => void openRun(runId)} />
      </>}
    </section>

    {detailId && (detailLoading ? <div className="research-drawer-overlay"><aside className="research-drawer" role="dialog" aria-modal="true"><LoadingState label="正在载入候选来源…" /><button className="button button-secondary" onClick={() => setDetailId("")}>关闭</button></aside></div> : candidateDetail && profile && <ResearchCandidateDrawer detail={candidateDetail} profile={profile.profile} language={detailLanguage} onLanguageChange={(language) => { setDetailLanguage(language); detailLanguageUpdater.current(language); }} noteBusy={actionBusy} noteError={actionError} onSaveSource={() => void saveSource(candidateDetail.candidate.id)} onSaveNote={(note) => void updateCandidateNote(note)} onReviewTerms={() => navigate("/terms?tab=candidates")} onClose={() => { setDetailId(""); setCandidateDetail(null); detailLanguageUpdater.current = () => undefined; }} onOpenEntity={(path) => { setDetailId(""); detailLanguageUpdater.current = () => undefined; navigate(path); }} />)}
    {runDetail && <ResearchRunDrawer run={runDetail} onClose={() => setRunDetail(null)} />}
    {dismissTargets && <ResearchDismissDialog count={dismissTargets.length} busy={actionBusy} onClose={() => setDismissTargets(null)} onSubmit={(reason, note) => void dismiss(dismissTargets, reason, note)} />}
    {shortlistTargets && <ResearchShortlistDialog count={shortlistTargets.length} busy={actionBusy} error={actionError} onClose={() => setShortlistTargets(null)} onSubmit={(note) => void shortlist(shortlistTargets, note)} />}
    {createNoteTarget && <ResearchCreateNoteDialog title={createNoteTarget.work.title} busy={actionBusy} suggestedCollectionId={createNoteTarget.analysis.suggested_collection ?? null} suggestedSection={createNoteTarget.analysis.suggested_section ?? null} allowedCollectionIds={profile?.profile.id === selectedProfileId ? profile.profile.context.collections : []} onClose={() => setCreateNoteTarget(null)} onCreate={(options) => void createNote(createNoteTarget.candidate.id, options)} />}
    {profileLayers}
      {sourceReview && <ResearchSourceReview draft={sourceReview} busy={actionBusy} error={actionError}
        onConfirm={() => {
          setActionBusy(true); setActionError("");
          void preflightDraft(sourceReview.id).then(async (result) => {
            if (!result.valid || result.conflict) throw new Error(result.errors.join("；") || "发布校验失败，请返回编辑处理冲突。");
            await publishDraft(sourceReview.id, sourceReview.revision);
            setSourceReview(null); refresh();
          }).catch((reason) => setActionError(errorMessage(reason))).finally(() => setActionBusy(false));
        }}
        onEdit={() => {
          const path = entityWorkspaceUrl("source", sourceReview.entity_id, { edit: true });
          setSourceReview(null); setActionError(""); navigate(path);
        }} />}
  </div>;
}
