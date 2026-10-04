import type { ResearchRun } from "./api";
import { Chip, formatDate } from "./ui";

export function ResearchRunList({
  runs,
  count,
  loading,
  onOpen,
}: {
  runs: ResearchRun[];
  count: number;
  loading: boolean;
  onOpen: (runId: string) => void;
}) {
  if (loading && runs.length === 0) return <div className="research-loading">Loading Research Runs…</div>;
  if (!runs.length) return <div className="empty-state"><span className="empty-mark">◷</span><strong>No Research Runs yet</strong><p>Scheduled discoveries and manual searches will appear here.</p></div>;
  return <div className="research-run-list">
    <div className="research-run-list-heading"><div><h2>Research Runs</h2><p>{count} recorded run{count === 1 ? "" : "s"} for this Profile</p></div></div>
    {runs.map((run) => <button className="research-run-row" key={run.id} onClick={() => onOpen(run.id)}>
      <span className={`research-run-mark research-run-${run.status}`} aria-hidden="true">{runMark(run.status)}</span>
      <span className="research-run-row-main"><strong>{formatDate(run.started_at)} · {run.trigger === "scheduled" ? "Scheduled" : "Manual"}</strong><small>{run.fetched_count} papers checked · {run.new_work_count} new works · {run.surfaced_count} candidates</small>{run.error_summary && <small className="research-run-row-issue">Run issues need review</small>}</span>
      <Chip tone={runTone(run.status)}>{run.status.replaceAll("_", " ")}</Chip>
      <span className="row-arrow" aria-hidden="true">↗</span>
    </button>)}
  </div>;
}

function runTone(status: ResearchRun["status"]): string {
  if (status === "success") return "green";
  if (status === "running") return "blue";
  if (status === "failed" || status === "interrupted") return "rose";
  if (["partial", "skipped_paused", "skipped_disabled", "skipped_inbox_full", "capacity_reached"].includes(status)) return "amber";
  return "neutral";
}

function runMark(status: ResearchRun["status"]): string {
  if (status === "success") return "✓";
  if (status === "running") return "◷";
  if (status === "failed" || status === "interrupted") return "!";
  return "·";
}

export function ResearchRunDrawer({ run, onClose }: { run: ResearchRun; onClose: () => void }) {
  const effective = run.effective_config;
  const profileSnapshot = isRecord(effective.profile) ? effective.profile : {};
  const lensOverrides = isRecord(effective.lens_overrides) ? effective.lens_overrides : {};
  const lensIds = Array.isArray(profileSnapshot.lenses)
    ? profileSnapshot.lenses
      .filter(isRecord)
      .filter((lens) => (typeof lensOverrides[lens.id as string] === "boolean" ? lensOverrides[lens.id as string] : lens.enabled) === true)
      .map((lens) => String(lens.title ?? lens.id))
    : [];
  const additionalQueryLensId = stringValue(effective.additional_query_lens);
  const additionalQueryLensTitle = additionalQueryLensId && Array.isArray(profileSnapshot.lenses)
    ? profileSnapshot.lenses.filter(isRecord).find((lens) => lens.id === additionalQueryLensId)?.title
    : null;
  const searchWindow = effective.manual_incremental === true
    ? "Incremental · scheduled watermark window (not advanced)"
    : Array.isArray(effective.manual_range)
      ? effective.manual_range.map((value) => String(value)).join(" → ")
      : run.trigger === "scheduled" ? "Scheduled coverage" : "Profile initial lookback";
  return <div className="research-drawer-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="research-drawer research-run-drawer" role="dialog" aria-modal="true" aria-labelledby="research-run-title">
      <header className="research-drawer-header"><div><p className="eyebrow">RUN INSPECTOR</p><h2 id="research-run-title">Research Run</h2><p>{run.id}</p></div><button className="workspace-drawer-close" aria-label="关闭运行详情" onClick={onClose}>×</button></header>
      <div className="research-drawer-body">
        <section className="research-run-overview">
          <div className="research-run-overview-status"><Chip tone={runTone(run.status)}>{run.status.replaceAll("_", " ")}</Chip><span>{run.trigger === "scheduled" ? "Scheduled research" : "Manual search"}</span></div>
          <div className="research-run-times"><Detail label="Started" value={formatDate(run.started_at)} /><Detail label="Finished" value={formatDate(run.finished_at)} /><Detail label="Duration" value={runDuration(run)} /></div>
          <div className="research-run-stats">{[["Results checked", run.fetched_count], ["New works", run.new_work_count], ["Candidates", run.surfaced_count]].map(([label, value]) => <div key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</div>
        </section>
        {run.error_summary && <section className="research-detail-section"><h3>Run issues</h3><p className="research-run-error">{run.error_summary}</p></section>}
        <details className="research-advanced-settings research-run-technical-details">
          <summary>Technical details</summary>
          <section className="research-detail-section"><h3>Run configuration</h3><Detail label="Profile" value={run.profile_id} /><Detail label="Trigger" value={run.trigger} /><Detail label="Run ID" value={run.id} /><Detail label="Lenses" value={lensIds.join(", ")} /></section>
          <section className="research-detail-section"><h3>Pipeline activity</h3><div className="research-run-stats">{[["Duplicates", run.duplicate_count], ["Filtered", run.deterministic_filtered_count], ["AI calls", run.analysis_attempt_count], ["AI analyses", run.analysis_counts_known ? run.analyzed_count : "—"]].map(([label, value]) => <div key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</div>{!run.analysis_counts_known && <p className="subtle-copy">Successful analysis totals were not recorded separately for this older Run.</p>}</section>
          <section className="research-detail-section"><h3>Provider activity</h3>{Object.entries(run.provider_summary).length ? Object.entries(run.provider_summary).map(([provider, summary]) => <div className="research-provider-row" key={provider}><div><Chip tone={summary.errors ? "amber" : "green"}>{provider}</Chip>{summary.circuit_open && <Chip tone="rose">circuit open</Chip>}</div><span>{summary.works} works · {summary.pages} pages · {summary.requests} requests · {summary.errors} errors</span></div>) : <p className="subtle-copy">No provider calls were recorded for this Run.</p>}</section>
          <section className="research-detail-section"><h3>Effective search</h3><Detail label="Breadth" value={stringValue(effective.breadth_override) ?? stringValue(isRecord(profileSnapshot.search) ? profileSnapshot.search.breadth : null) ?? "balanced"} /><Detail label="Search window" value={searchWindow} /><Detail label="Additional queries" value={Array.isArray(effective.additional_queries) ? effective.additional_queries.join(" · ") : "—"} /><Detail label="Additional query Lens" value={additionalQueryLensId ? String(additionalQueryLensTitle ?? additionalQueryLensId) + " (" + additionalQueryLensId + ")" : "—"} /><Detail label="Configuration hash" value={run.profile_content_hash} /></section>
        </details>
      </div>
      <footer className="research-drawer-footer"><span>Provider counts and errors are retained with this Runtime Run.</span><button className="button button-secondary" onClick={onClose}>Done</button></footer>
    </aside>
  </div>;
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return <div className="research-detail-row"><span>{label}</span><strong>{value || "—"}</strong></div>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function runDuration(run: ResearchRun) {
  if (!run.finished_at) return run.status === "running" ? "In progress" : "—";
  const seconds = Math.max(0, Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000));
  if (seconds < 60) return seconds + " sec";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes + " min" + (remainingSeconds ? " " + remainingSeconds + " sec" : "");
}
