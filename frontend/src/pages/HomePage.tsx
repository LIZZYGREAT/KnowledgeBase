import {
  getTermDiscoveryState, getUiSummary, listRecentlyModified, listResearchProfiles,
  listTermCandidates, listUsage,
  listResearchCandidates, queueResearchRun,
  type ResearchProfileSummary, type TermCandidate, type TermDiscoveryLane,
  type TermDiscoveryState, type UiSummary,
} from "../api";
import { MarkdownContent } from "../Markdown";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState, formatDate } from "../ui";
import { readString, useResource, type Navigate, type SelectEntity } from "./PageShared";
import { useState } from "react";

interface HomeCriticalData {
  summary: UiSummary;
  termDiscovery: TermDiscoveryState;
  pendingCandidates: TermCandidate[];
  researchProfiles: ResearchProfileSummary[];
}

export function HomePage({ onOpen, navigate }: { onOpen: SelectEntity; navigate: Navigate }) {
  const [finding, setFinding] = useState(false);
  const [findingFeedback, setFindingFeedback] = useState<{ type: "status" | "error"; message: string } | null>(null);
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
  const recommendations = useResource("home-featured-research", () => listResearchCandidates({ status: "new", sort: "recommended", limit: 6 }));

  if (critical.loading) return <LoadingState />;
  if (critical.error || !critical.data) return <ErrorState message={critical.error} retry={critical.retry} />;
  const { summary, termDiscovery, pendingCandidates, researchProfiles } = critical.data;
  const papers = (recommendations.data?.candidates ?? []).filter((item, index, all) => all.findIndex((other) => other.work.id === item.work.id) === index).slice(0, 2);
  const terms = pendingCandidates.filter((candidate) => candidate.evidence.some((item) => !item.origin_rejected && Boolean(item.context_excerpt?.trim())) && Boolean(candidate.discovery_assessment?.why_now || candidate.evidence.find((item) => !item.origin_rejected)?.rationale)).slice(0, Math.max(0, 3 - papers.length));
  async function findNext() {
    const profile = researchProfiles.find((item) => item.enabled && !(item.paused_until && Date.parse(item.paused_until) > Date.now()) && item.inbox.remaining > 0);
    if (!profile) { setFindingFeedback({ type: "status", message: "请先设置或恢复一个研究方向，或处理已满的 Inbox。" }); return; }
    setFinding(true); setFindingFeedback(null);
    try {
      await queueResearchRun(profile.id, { lenses: profile.enabled_lens_ids, date_range: { mode: "incremental" } });
      setFindingFeedback({ type: "status", message: "寻找下一步已加入研究队列，可在 Research 查看结果。" });
    }
    catch (reason) { setFindingFeedback({ type: "error", message: reason instanceof Error ? reason.message : "请求失败，请重试。" }); }
    finally { setFinding(false); }
  }
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
  const established = readLabelArray(Array.isArray(knowledge.established) ? knowledge.established.filter((item) => asRecord(item).review_status === "approved" && Boolean(asRecord(item).content_excerpt)) : []);
  const learning = readLabelArray(knowledge.learning);
  const coreGaps = pendingCandidates
    .filter((candidate) => candidate.discovery_assessment?.recommendation_level === "core_gap")
    .map((candidate) => candidate.display_name);

  return (
    <div className="page-stack dashboard-page">
      <header className="dashboard-heading">
        <div><p className="eyebrow">KNOWLEDGE DASHBOARD</p><h1>下一步值得学习什么。</h1><p>从已审核知识出发，查看有来源、有理由的论文与 Term 建议。</p></div>
        <button className="dashboard-search-link" type="button" onClick={() => navigate("/search")}>搜索知识库 <span aria-hidden="true">⌕</span></button>
      </header>

      <section className="dashboard-featured surface" aria-labelledby="featured-knowledge-title">
        <div className="section-heading"><div><h2 id="featured-knowledge-title">下一步值得了解</h2><p>少量有依据的知识建议，由你决定是否接受。</p></div><div className="home-featured-actions"><button type="button" className="button button-primary" disabled={finding} onClick={() => void findNext()}>{finding ? "正在加入队列…" : "寻找下一步"}</button>{findingFeedback && <p className={findingFeedback.type === "error" ? "home-finding-feedback error" : "home-finding-feedback"} role={findingFeedback.type === "error" ? "alert" : "status"}>{findingFeedback.message}</p>}</div></div>
        {recommendations.loading && <p>正在读取论文建议…</p>}
        {recommendations.error && <p className="home-recommendation-error" role="alert">论文建议读取失败。<button type="button" className="button button-secondary" onClick={recommendations.retry}>重试</button></p>}
        <div className="dashboard-featured-grid">
          {papers.map((item) => <article key={item.candidate.id}>
            <Chip>{item.analysis.readiness === "low" ? "拓展阅读" : "优先阅读"}</Chip>
            <h3>{item.work.title}</h3>
            <RecommendationReason content={item.candidate.review_overrides?.why_relevant_zh ?? item.analysis.why_relevant_zh ?? item.analysis.why_relevant ?? ""} />
            {item.analysis.existing_relations.length > 0 && <div className="home-recommendation-related"><span>相关知识</span>{item.analysis.existing_relations.slice(0, 3).map((relation) => <button className="text-button" type="button" key={`${relation.entity_type}:${relation.entity_id}`} onClick={() => navigate(relation.entity_type === "document" ? `/documents/${encodeURIComponent(relation.entity_id)}` : relation.entity_type === "term" ? `/terms/${encodeURIComponent(relation.entity_id)}` : `/research?work_id=${encodeURIComponent(item.work.id)}`)}>{relation.entity_id}</button>)}</div>}
            <div className="home-recommendation-card-actions"><button type="button" className="button button-secondary" onClick={() => navigate(`/research?work_id=${encodeURIComponent(item.work.id)}`)}>查看并审核论文</button></div>
          </article>)}
          {terms.map((candidate) => <article key={candidate.id}>
            <Chip>Term 建议</Chip>
            <h3>{candidate.display_name}</h3>
            <RecommendationReason content={candidate.discovery_assessment?.why_now || candidate.evidence.find((item) => !item.origin_rejected)?.rationale || ""} />
            <p className="home-recommendation-sources"><strong>来源</strong> {candidate.evidence.filter((item) => !item.origin_rejected).map((item) => item.origin_title || item.origin_id).slice(0, 2).join(" · ") || "暂无来源信息"}</p>
            <div className="home-recommendation-card-actions"><button type="button" className="button button-secondary" onClick={() => navigate("/terms?tab=candidates")}>查看并审核 Term</button></div>
          </article>)}
        </div>
        {!recommendations.loading && !papers.length && !terms.length && <p>暂时没有合适的精选建议。继续维护已审核知识，或按需寻找下一步。</p>}
        <div className="dashboard-featured-footer"><button type="button" className="button button-quiet" onClick={() => navigate("/research")}>完整论文列表</button><button type="button" className="button button-quiet" onClick={() => navigate("/terms?tab=candidates")}>完整 Term 列表</button></div>
      </section>

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
            <ContextList title="关注线索" items={learning} empty="暂无历史关注线索。" />
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

function RecommendationReason({ content }: { content: string }) {
  const plainText = content
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/[>*_~`]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const characters = Array.from(plainText);
  const limit = 180;
  const summary = characters.length > limit ? `${characters.slice(0, limit).join("")}…` : plainText;

  return <div className="home-recommendation-reason">
    <span className="home-recommendation-reason-label">推荐理由</span>
    <p className="home-recommendation-reason-summary">{summary || "暂未提供推荐理由。"}</p>
    {characters.length > limit && <details className="home-recommendation-full-details">
      <summary>展开完整理由</summary>
      <div className="home-recommendation-full"><MarkdownContent content={content} /></div>
    </details>}
  </div>;
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
