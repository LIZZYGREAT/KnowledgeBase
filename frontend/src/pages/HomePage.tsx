import {
  getTermDiscoveryState, getUiSummary, listRecentlyModified, listResearchProfiles,
  listTermCandidates, listUsage,
  type ResearchProfileSummary, type TermCandidate, type TermDiscoveryLane,
  type TermDiscoveryState, type UiSummary,
} from "../api";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState, formatDate } from "../ui";
import { readString, useResource, type Navigate, type SelectEntity } from "./PageShared";

interface HomeCriticalData {
  summary: UiSummary;
  termDiscovery: TermDiscoveryState;
  pendingCandidates: TermCandidate[];
  researchProfiles: ResearchProfileSummary[];
}

export function HomePage({ onOpen, navigate }: { onOpen: SelectEntity; navigate: Navigate }) {
  const critical = useResource("home-critical", async (): Promise<HomeCriticalData> => {
    const [summary, termDiscovery, pendingCandidates, researchProfiles] = await Promise.all([
      getUiSummary(),
      getTermDiscoveryState(),
      listTermCandidates("pending"),
      listResearchProfiles(),
    ]);
    return { summary, termDiscovery, pendingCandidates, researchProfiles };
  });
  const recentlyViewed = useResource("home-recent-usage", () => listUsage("recent"));
  const recentlyModified = useResource("home-recent-modified", () => listRecentlyModified());

  if (critical.loading) return <LoadingState />;
  if (critical.error || !critical.data) return <ErrorState message={critical.error} retry={critical.retry} />;
  const { summary, termDiscovery, pendingCandidates, researchProfiles } = critical.data;
  const snapshot = asRecord(termDiscovery.last_run?.snapshot);
  const snapshotFocus = asRecord(snapshot.focus);
  const knowledge = asRecord(snapshot.knowledge);
  const hasEffectiveFocus = Array.isArray(snapshot.effective_focus);
  const legacyFocus = [
    ...(termDiscovery.settings.focus_override ? [termDiscovery.settings.focus_override] : []),
    ...readLabelArray(snapshotFocus.recent_terms),
    ...readStringArray(snapshotFocus.recent_topics),
    ...readStringArray(snapshotFocus.recent_domains),
    ...readStringArray(snapshotFocus.explicit),
  ];
  const focusItems = hasEffectiveFocus
    ? readStringArray(snapshot.effective_focus)
    : Array.from(new Set(legacyFocus.length ? legacyFocus : readStringArray(snapshotFocus.explicit)));
  const established = readLabelArray(knowledge.established);
  const learning = readLabelArray(knowledge.learning);
  const coreGaps = pendingCandidates
    .filter((candidate) => candidate.discovery_assessment?.recommendation_level === "core_gap")
    .map((candidate) => candidate.display_name);

  return (
    <div className="page-stack dashboard-page">
      <header className="dashboard-heading">
        <div><p className="eyebrow">KNOWLEDGE DASHBOARD</p><h1>知道你正在学什么，以及下一步值得补什么。</h1><p>查看待处理工作、当前学习脉络和 Agent 最近运行情况。</p></div>
        <button className="dashboard-search-link" type="button" onClick={() => navigate("/search")}>搜索知识库 <span aria-hidden="true">⌕</span></button>
      </header>

      <section className="dashboard-workload surface" aria-labelledby="dashboard-workload-title">
        <div className="section-heading"><div><h2 id="dashboard-workload-title">现在有什么要处理？</h2><p>优先显示需要你作出判断的事项。</p></div><button className="text-button" type="button" onClick={() => navigate("/new-note")}>新建笔记</button></div>
        <div className="dashboard-workload-grid">
          <WorkloadCard title="Term Candidates" value={`${termDiscovery.open_count} / ${termDiscovery.global_capacity}`} detail={`${summary.terms_pending} 待审阅 · ${summary.term_drafts} 个 Term Draft`} onClick={() => navigate("/terms?tab=candidates")} />
          <WorkloadCard title="Term Drafts" value={summary.term_drafts} detail="等待继续编辑或发布" onClick={() => navigate("/terms?tab=candidates")} />
          <WorkloadCard title="Research Inbox" value={`${summary.research_new} / ${summary.research_capacity}`} detail={`${summary.research_profiles} 个 Research Profile`} onClick={() => navigate("/research")} />
          <WorkloadCard title="Pending Imports" value={summary.pending_imports} detail="等待检查并创建 Draft" onClick={() => navigate("/library?tab=import")} />
          <WorkloadCard title="Maintenance" value={summary.maintenance} detail="审阅、修订与过期标注" onClick={() => navigate("/review")} />
        </div>
        <div className="dashboard-primary-actions"><button className="button button-primary" type="button" onClick={() => navigate("/terms?tab=candidates")}>Review Terms</button><button className="button button-secondary" type="button" onClick={() => navigate("/research")}>Open Research</button></div>
      </section>

      <div className="dashboard-lower-grid">
        <section className="dashboard-panel surface" aria-labelledby="learning-context-title">
          <div className="section-heading"><div><h2 id="learning-context-title">Learning Context</h2><p>最近一次 Term Discovery 使用的知识状态快照。</p></div><Chip>{termDiscovery.last_run ? `更新于 ${formatDate(termDiscovery.last_run.started_at)}` : "尚无快照"}</Chip></div>
          <div className="learning-context-grid">
            <ContextList title="Current Focus" items={focusItems} empty="完成一次 Discovery 后显示当前 Focus。" />
            <ContextList title="Established" items={established} empty="尚无已建立的 Term。" />
            <ContextList title="Learning" items={learning} empty="尚无正在学习的 Term。" />
            <ContextList title="Core Gaps" items={coreGaps} empty="当前没有待审阅的 Core Gap。" />
          </div>
        </section>

        <section className="dashboard-panel surface" aria-labelledby="agent-status-title">
          <div className="section-heading"><div><h2 id="agent-status-title">Agent Status</h2><p>自动发现与研究任务的最近状态。</p></div><button className="text-button" type="button" onClick={() => navigate("/terms?tab=discovery")}>打开 Discovery</button></div>
          <div className="agent-status-list">
            {TERM_LANES.map((lane) => <AgentStatusRow key={lane.id} title={lane.title} state={termLaneState(lane.id, termDiscovery)} lastResult={termLaneResult(lane.id, termDiscovery)} />)}
            <AgentStatusRow title="Research" state={researchAgentState(researchProfiles)} lastResult={researchAgentResult(researchProfiles)} onOpen={() => navigate("/research")} />
          </div>
        </section>
      </div>

      <section className="dashboard-panel dashboard-recent surface" aria-labelledby="recent-activity-title">
        <div className="section-heading"><div><h2 id="recent-activity-title">Recent Activity</h2><p>最近阅读与最近修改，位于工作台下方。</p></div><button className="text-button" type="button" onClick={() => navigate("/library")}>打开 Library</button></div>
        <div className="recent-activity-grid">
          <div><h3>最近阅读</h3>{recentlyViewed.loading ? <p className="subtle-copy">加载中…</p> : recentlyViewed.error ? <button className="text-button" type="button" onClick={recentlyViewed.retry}>加载失败，重试</button> : recentlyViewed.data?.length ? <div className="entity-list compact-list">{recentlyViewed.data.map((entry) => <EntityRow key={entry.entity_id} title={entry.title} detail={`${entry.view_count} 次阅读 · ${formatDate(entry.last_viewed_at)}`} onClick={() => onOpen("document", entry.entity_id)} />)}</div> : <EmptyState title="还没有阅读记录" description="打开一篇笔记后，最近阅读会显示在这里。" />}</div>
          <div><h3>最近修改</h3>{recentlyModified.loading ? <p className="subtle-copy">加载中…</p> : recentlyModified.error ? <button className="text-button" type="button" onClick={recentlyModified.retry}>加载失败，重试</button> : recentlyModified.data?.length ? <div className="entity-list compact-list">{recentlyModified.data.map((entity) => <EntityRow key={entity.id} title={entity.title} detail={`修改于 ${formatDate(entity.modified_at)}`} onClick={() => onOpen("document", entity.id)} />)}</div> : <EmptyState title="暂无最近修改" description="发布后的 Document 会显示在这里。" />}</div>
        </div>
      </section>
    </div>
  );
}

const TERM_LANES: Array<{ id: TermDiscoveryLane; title: string }> = [
  { id: "concept", title: "Concept Discovery" },
  { id: "entity", title: "Entity Discovery" },
  { id: "vocabulary", title: "Vocabulary Discovery" },
];

function WorkloadCard({ title, value, detail, onClick }: { title: string; value: string | number; detail: string; onClick: () => void }) {
  return <button className="workload-card" type="button" onClick={onClick}><span>{title}</span><strong>{value}</strong><small>{detail}</small></button>;
}

function ContextList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return <div className="context-list"><h3>{title}</h3>{items.length ? <ul>{items.slice(0, 5).map((item) => <li key={item}>{item}</li>)}</ul> : <p>{empty}</p>}</div>;
}

function AgentStatusRow({ title, state, lastResult, onOpen }: { title: string; state: string; lastResult: string; onOpen?: () => void }) {
  return <div className="agent-status-row">{onOpen ? <button type="button" onClick={onOpen}>{title}</button> : <strong>{title}</strong>}<Chip tone={state === "ready" ? "green" : state.startsWith("failed") ? "rose" : "amber"}>{state}</Chip><small>{lastResult}</small></div>;
}

function termLaneState(lane: TermDiscoveryLane, state: TermDiscoveryState) {
  if (!state.settings.enabled_lanes.includes(lane)) return "paused";
  if (state.open_count >= state.global_capacity || (state.lane_open[lane] ?? 0) >= (state.lane_capacity[lane] ?? 0) || state.daily_remaining <= 0) return "paused · capacity reached";
  return "ready";
}

function termLaneResult(lane: TermDiscoveryLane, state: TermDiscoveryState) {
  const run = state.last_run;
  if (!run) return "No run yet";
  const created = run.items.filter((item) => item.lane === lane && item.outcome === "created").length;
  return `${runStatusLabel(run.status)} · ${created} new · ${formatDate(run.started_at)}`;
}

function researchAgentState(profiles: ResearchProfileSummary[]) {
  if (!profiles.length) return "not configured";
  const activeProfiles = profiles.filter((profile) => profile.enabled && !(profile.paused_until && Date.parse(profile.paused_until) > Date.now()));
  if (!activeProfiles.length) return "paused";
  if (activeProfiles.every((profile) => profile.inbox.remaining <= 0)) return "paused · Inbox full";
  return "ready";
}

function researchAgentResult(profiles: ResearchProfileSummary[]) {
  const latest = profiles.flatMap((profile) => profile.latest_run ? [profile.latest_run] : [])
    .sort((left, right) => right.started_at.localeCompare(left.started_at))[0];
  return latest ? `${runStatusLabel(latest.status)} · ${latest.surfaced_count} surfaced · ${formatDate(latest.started_at)}` : "No run yet";
}

function runStatusLabel(status: string) {
  const labels: Record<string, string> = {
    success: "success",
    partial: "partial",
    failed: "failed",
    interrupted: "interrupted",
    skipped_capacity: "skipped · capacity reached",
    skipped_paused: "paused",
    skipped_disabled: "paused · disabled",
    skipped_inbox_full: "skipped · Inbox full",
    capacity_reached: "capacity reached",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function readLabelArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => readString(asRecord(item).title)).filter(Boolean) : [];
}
