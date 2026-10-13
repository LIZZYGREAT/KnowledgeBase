import type { ResearchRun } from "./api";
import { Chip, formatDate } from "./ui";

export function researchStatusLabel(status: string): string {
  const labels: Record<string, string> = { success: "已完成", running: "正在检索", partial: "部分完成", failed: "失败", interrupted: "已中断", skipped_paused: "已暂停", skipped_disabled: "已停用", skipped_inbox_full: "待看论文已满", capacity_reached: "已达处理上限", skipped_capacity: "已达处理上限" };
  return labels[status] ?? status;
}

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
  if (loading && runs.length === 0) return <div className="research-loading">正在读取检索记录…</div>;
  if (!runs.length) return <div className="empty-state"><span className="empty-mark">◷</span><strong>暂无检索记录</strong><p>自动发现和手动检索的结果会显示在这里。</p></div>;
  return <div className="research-run-list">
    <div className="research-run-list-heading"><div><h2>检索记录</h2><p>当前研究方向有 {count} 条检索记录</p></div></div>
    {runs.map((run) => <button className="research-run-row" key={run.id} onClick={() => onOpen(run.id)}>
      <span className={`research-run-mark research-run-${run.status}`} aria-hidden="true">{runMark(run.status)}</span>
      <span className="research-run-row-main"><strong>{formatDate(run.started_at)} · {run.trigger === "scheduled" ? "自动检索" : "手动检索"}</strong><small>{run.fetched_count} 篇已检查 · {run.new_work_count} 篇新增论文 · {run.surfaced_count} 篇推荐</small>{run.error_summary && <small className="research-run-row-issue">需要查看检索中的问题</small>}</span>
      <Chip tone={runTone(run.status)}>{researchStatusLabel(run.status)}</Chip>
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
    ? "Incremental · 自动检索进度 window (not advanced)"
    : Array.isArray(effective.manual_range)
      ? effective.manual_range.map((value) => String(value)).join(" → ")
      : run.trigger === "scheduled" ? "Scheduled coverage" : "研究方向 initial lookback";
  return <div className="research-drawer-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="research-drawer research-run-drawer" role="dialog" aria-modal="true" aria-labelledby="research-run-title">
      <header className="research-drawer-header"><div><p className="eyebrow">检索详情</p><h2 id="research-run-title">检索记录</h2><p>{run.id}</p></div><button className="workspace-drawer-close" aria-label="关闭运行详情" onClick={onClose}>×</button></header>
      <div className="research-drawer-body">
        <section className="research-run-overview">
          <div className="research-run-overview-status"><Chip tone={runTone(run.status)}>{researchStatusLabel(run.status)}</Chip><span>{run.trigger === "scheduled" ? "自动检索" : "手动检索"}</span></div>
          <div className="research-run-times"><Detail label="开始时间" value={formatDate(run.started_at)} /><Detail label="结束时间" value={formatDate(run.finished_at)} /><Detail label="用时" value={runDuration(run)} /></div>
          <div className="research-run-stats">{[["已检查论文", run.fetched_count], ["新增论文", run.new_work_count], ["待处理项", run.surfaced_count]].map(([label, value]) => <div key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</div>
        </section>
        {run.error_summary && <section className="research-detail-section"><h3>检索中的问题</h3><p className="research-run-error">{run.error_summary}</p></section>}
        <details className="research-advanced-settings research-run-technical-details">
          <summary>技术详情</summary>
          <section className="research-detail-section"><h3>Run configuration</h3><Detail label="研究方向" value={run.profile_id} /><Detail label="Trigger" value={run.trigger} /><Detail label="Run ID" value={run.id} /><Detail label="Lenses" value={lensIds.join(", ")} /></section>
          <section className="research-detail-section"><h3>Pipeline activity</h3><div className="research-run-stats">{[["Duplicates", run.duplicate_count], ["Filtered", run.deterministic_filtered_count], ["AI calls", run.analysis_attempt_count], ["AI analyses", run.analysis_counts_known ? run.analyzed_count : "—"]].map(([label, value]) => <div key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</div>{!run.analysis_counts_known && <p className="subtle-copy">Successful analysis totals were not recorded separately for this older Run.</p>}</section>
          <section className="research-detail-section"><h3>Provider activity</h3>{Object.entries(run.provider_summary).length ? Object.entries(run.provider_summary).map(([provider, summary]) => <div className="research-provider-row" key={provider}><div><Chip tone={summary.errors ? "amber" : "green"}>{provider}</Chip>{summary.circuit_open && <Chip tone="rose">circuit open</Chip>}</div><span>{summary.works} works · {summary.pages} pages · {summary.requests} requests · {summary.errors} errors</span></div>) : <p className="subtle-copy">No provider calls were recorded for this Run.</p>}</section>
          <section className="research-detail-section"><h3>Effective search</h3><Detail label="Breadth" value={stringValue(effective.breadth_override) ?? stringValue(isRecord(profileSnapshot.search) ? profileSnapshot.search.breadth : null) ?? "balanced"} /><Detail label="搜索 window" value={searchWindow} /><Detail label="Additional queries" value={Array.isArray(effective.additional_queries) ? effective.additional_queries.join(" · ") : "—"} /><Detail label="Additional query 检索主题" value={additionalQueryLensId ? String(additionalQueryLensTitle ?? additionalQueryLensId) + " (" + additionalQueryLensId + ")" : "—"} /><Detail label="Configuration hash" value={run.profile_content_hash} /></section>
        </details>
      </div>
      <footer className="research-drawer-footer"><span>请求次数与异常保留在本次检索的技术详情中。</span><button className="button button-secondary" onClick={onClose}>完成</button></footer>
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
