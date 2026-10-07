import { useEffect, useState, type FormEvent } from "react";
import {
  getTermDiscoveryState,
  listTermDiscoveryRuns,
  runTermDiscovery,
  updateTermDiscoverySettings,
  type TermDiscoveryLane,
  type TermDiscoveryRun,
  type TermDiscoverySettings,
  type TermDiscoveryState,
} from "../api";
import { errorMessage } from "../errors";
import { Chip, ErrorState, LoadingState } from "../ui";

const LANES: Array<{ id: TermDiscoveryLane; title: string; description: string }> = [
  { id: "concept", title: "Concept", description: "方法、机制、理论和稳定概念" },
  { id: "entity", title: "Entity", description: "值得重复识别的模型、数据集和系统" },
  { id: "vocabulary", title: "Vocabulary", description: "影响科研论文理解的专业词汇" },
];

export function TermDiscoveryPanel() {
  const [state, setState] = useState<TermDiscoveryState | null>(null);
  const [runs, setRuns] = useState<TermDiscoveryRun[]>([]);
  const [draft, setDraft] = useState<TermDiscoverySettings | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    const [nextState, nextRuns] = await Promise.all([
      getTermDiscoveryState(),
      listTermDiscoveryRuns(20),
    ]);
    setState(nextState);
    setDraft(nextState.settings);
    setSourceText(nextState.settings.source_preferences.join(", "));
    setRuns(nextRuns);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    void Promise.all([getTermDiscoveryState(), listTermDiscoveryRuns(20)])
      .then(([nextState, nextRuns]) => {
        if (!active) return;
        setState(nextState);
        setDraft(nextState.settings);
        setSourceText(nextState.settings.source_preferences.join(", "));
        setRuns(nextRuns);
      })
      .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function toggleLane(lane: TermDiscoveryLane) {
    setDraft((current) => {
      if (!current) return current;
      const enabled = current.enabled_lanes.includes(lane);
      return {
        ...current,
        enabled_lanes: enabled
          ? current.enabled_lanes.filter((item) => item !== lane)
          : [...current.enabled_lanes, lane],
      };
    });
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const nextState = await updateTermDiscoverySettings({
        ...draft,
        source_preferences: sourceText.split(",").map((item) => item.trim()).filter(Boolean),
        focus_override: draft.focus_override?.trim() || null,
      });
      setState(nextState);
      setDraft(nextState.settings);
      setSourceText(nextState.settings.source_preferences.join(", "));
      setNotice("Discovery 设置已保存。");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const run = await runTermDiscovery();
      const [nextState, nextRuns] = await Promise.all([
        getTermDiscoveryState(),
        listTermDiscoveryRuns(20),
      ]);
      setState(nextState);
      setDraft(nextState.settings);
      setRuns(nextRuns);
      setNotice(run.candidate_count
        ? `本次新增 ${run.candidate_count} 个 Term Candidate。`
        : "本次没有新增 Candidate；可查看运行记录了解原因。");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在读取 Discovery 状态…" />;
  if (error && !state) return <ErrorState message={error} retry={() => { setLoading(true); void refresh().catch((reason: unknown) => setError(errorMessage(reason))).finally(() => setLoading(false)); }} />;
  if (!state || !draft) return null;

  return (
    <section className="term-discovery-panel" aria-label="Term Discovery">
      <div className="term-discovery-overview surface">
        <div className="term-discovery-overview-heading">
          <div><span className="section-kicker">FOCUS-AWARE RECOMMENDATIONS</span><h2>Discovery</h2><p>从本地 PDF、Notes 和可选的外部摘要中挑选少量适合当前学习进度的 Term。</p></div>
          <button className="button button-primary" type="button" disabled={busy} onClick={() => void runNow()}>{busy ? "正在运行…" : "Run Now"}</button>
        </div>
        <div className="term-discovery-capacity-grid">
          <div><span>Open Candidates</span><strong>{state.open_count} / {state.global_capacity}</strong></div>
          <div><span>Today remaining</span><strong>{state.daily_remaining}</strong></div>
          {LANES.map((lane) => <div key={lane.id}><span>{lane.title}</span><strong>{state.lane_open[lane.id] ?? 0} / {state.lane_capacity[lane.id] ?? 0}</strong></div>)}
        </div>
        {state.last_run && <p className="term-discovery-last-run">Last run · {state.last_run.status.replaceAll("_", " ")} · {new Date(state.last_run.started_at).toLocaleString()}</p>}
      </div>

      <form className="term-discovery-settings surface" onSubmit={(event) => void saveSettings(event)}>
        <div className="section-heading"><div><h3>Discovery settings</h3><p>Focus 优先复用 Research Profile；这里只保存少量运行偏好。</p></div><button className="button button-secondary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save settings"}</button></div>
        <div className="term-discovery-lanes">
          {LANES.map((lane) => <label className="term-discovery-lane" key={lane.id}>
            <input type="checkbox" checked={draft.enabled_lanes.includes(lane.id)} onChange={() => toggleLane(lane.id)} />
            <span><strong>{lane.title}</strong><small>{lane.description}</small></span>
            <span className="term-discovery-lane-quota"><small>容量</small><input type="number" min={1} max={12} value={draft.lane_capacities[lane.id]} onChange={(event) => setDraft((current) => current ? { ...current, lane_capacities: { ...current.lane_capacities, [lane.id]: Number(event.target.value) } } : current)} aria-label={`${lane.title} capacity`} /></span>
          </label>)}
        </div>
        <div className="term-discovery-setting-fields">
          <label className="field-label">每日新增上限<input type="number" min={1} max={12} value={draft.daily_max_new} onChange={(event) => setDraft((current) => current ? { ...current, daily_max_new: Number(event.target.value) } : current)} /></label>
          <label className="field-label">Focus override（可选）<input value={draft.focus_override ?? ""} maxLength={500} onChange={(event) => setDraft((current) => current ? { ...current, focus_override: event.target.value || null } : current)} placeholder="沿用 Research Profile 的方向" /></label>
          <label className="field-label">优先 Source ID（逗号分隔）<input value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="例如 source-alpha, source-beta" /></label>
        </div>
        <label className="term-discovery-external-setting">
          <input type="checkbox" checked={draft.external_enabled} onChange={(event) => setDraft((current) => current ? { ...current, external_enabled: event.target.checked } : current)} />
          <span><strong>启用 Wikipedia 外部发现</strong><small>开启后，每次手动或定时运行最多发送一次 Focus 查询并读取两条摘要；Focus 查询会发给 Wikipedia，摘要会交给 AI 分析。只用于 Concept 和 Entity。</small></span>
        </label>
      </form>

      {notice && <p className="editor-notice success-notice" role="status">{notice}</p>}
      {error && <p className="error-copy" role="alert">{error}</p>}

      <section className="term-discovery-history surface" aria-label="Discovery Run History">
        <div className="section-heading"><div><h3>Run History</h3><p>Stretch 建议保留在运行结果中，不会占用 Candidate Inbox。</p></div><span className="count-label">{runs.length} runs</span></div>
        {runs.length ? <div className="term-discovery-run-list">{runs.map((run) => <details className="term-discovery-run" key={run.id}>
          <summary><span><Chip tone={run.status === "success" ? "green" : run.status === "partial" ? "amber" : "neutral"}>{run.status.replaceAll("_", " ")}</Chip> {new Date(run.started_at).toLocaleString()}</span><strong>{run.candidate_count} new</strong></summary>
          <div className="term-discovery-run-detail">
            <p>预算：Concept {run.lane_budgets.concept ?? 0} · Entity {run.lane_budgets.entity ?? 0} · Vocabulary {run.lane_budgets.vocabulary ?? 0}</p>
            <p>模型建议 {Object.values(run.raw_counts).reduce((sum, value) => sum + value, 0)} · 过滤 {Object.values(run.filtered_counts).reduce((sum, value) => sum + value, 0)}</p>
            {run.error_summary && <p className="error-copy">{run.error_summary}</p>}
            {run.items.map((item) => <article className="term-discovery-result" key={item.id}>
              <div><strong>{item.mention}</strong><Chip>{item.lane}</Chip><Chip tone={item.outcome === "created" ? "green" : item.outcome === "stretch" ? "amber" : "neutral"}>{item.outcome}</Chip><Chip>{item.assessment.readiness} readiness</Chip></div>
              <p>{item.assessment.why_now}</p>
              {(item.assessment.known_prerequisites.length > 0 || item.assessment.missing_prerequisites.length > 0) && <small>已有：{item.assessment.known_prerequisites.join("、") || "—"} · 缺少：{item.assessment.missing_prerequisites.join("、") || "—"}</small>}
              {item.rationale && <blockquote>{item.context_excerpt}</blockquote>}
            </article>)}
          </div>
        </details>)}</div> : <p className="term-discovery-empty">还没有运行记录。开启需要的 Lane 后，可手动运行一次。</p>}
      </section>
    </section>
  );
}
