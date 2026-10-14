import { useEffect, useState, type FormEvent } from "react";
import {
  getLearningContext,
  getTermDiscoveryState,
  listTermDiscoveryRuns,
  runTermDiscovery,
  updateTermDiscoverySettings,
  type TermDiscoveryLane,
  type TermDiscoveryRun,
  type TermDiscoveryMode,
  type TermDiscoverySettings,
  type TermDiscoveryState,
  type LearningContextOverview,
} from "../api";
import { errorMessage } from "../errors";
import { Chip, ErrorState, LoadingState } from "../ui";

const LANES: Array<{ id: TermDiscoveryLane; title: string; description: string }> = [
  { id: "concept", title: "概念", description: "方法、机制、理论和稳定概念" },
  { id: "entity", title: "命名实体", description: "值得重复识别的模型、数据集和系统" },
  { id: "vocabulary", title: "专业词汇", description: "影响科研论文理解的专业词汇" },
];

const LANE_LABELS: Record<TermDiscoveryLane, string> = {
  concept: "概念",
  entity: "命名实体",
  vocabulary: "专业词汇",
};

const RUN_STATUS_LABELS: Record<TermDiscoveryRun["status"], string> = {
  success: "成功",
  partial: "部分完成",
  failed: "失败",
  skipped_capacity: "容量已满",
  skipped_disabled: "已停用",
};

const OUTCOME_LABELS: Record<TermDiscoveryRun["items"][number]["outcome"], string> = {
  created: "已加入待处理",
  stretch: "拓展建议",
  duplicate: "已存在",
  filtered: "未纳入",
  rejected: "已拒绝",
  error: "处理失败",
};

const READINESS_LABELS: Record<TermDiscoveryRun["items"][number]["assessment"]["readiness"], string> = {
  high: "高",
  medium: "中",
  low: "低",
};

export function TermDiscoveryPanel({ navigate }: { navigate?: (path: string) => void }) {
  const [state, setState] = useState<TermDiscoveryState | null>(null);
  const [runs, setRuns] = useState<TermDiscoveryRun[]>([]);
  const [learningContext, setLearningContext] = useState<LearningContextOverview | null>(null);
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

  useEffect(() => {
    let active = true;
    void getLearningContext()
      .then((context) => { if (active) setLearningContext(context); })
      .catch(() => { if (active) setLearningContext(null); });
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
      setNotice("发现术语设置已保存。");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runNow(discoveryMode: TermDiscoveryMode) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (draft && state) {
        const settings = { ...draft, source_preferences: sourceText.split(",").map((item) => item.trim()).filter(Boolean), focus_override: draft.focus_override?.trim() || null };
        if (JSON.stringify(settings) !== JSON.stringify(state.settings)) await updateTermDiscoverySettings(settings);
      }
      const run = await runTermDiscovery(discoveryMode);
      const [nextState, nextRuns] = await Promise.all([
        getTermDiscoveryState(),
        listTermDiscoveryRuns(20),
      ]);
      setState(nextState);
      setDraft(nextState.settings);
      setRuns(nextRuns);
      setSourceText(nextState.settings.source_preferences.join(", "));
      const modeLabel = discoveryMode === "general" ? "通用发现" : "按学习进度发现";
      setNotice(run.status === "failed" ? `${modeLabel}失败，请查看发现记录中的原因。` : `${modeLabel}${run.status === "partial" ? "部分完成。" : "完成。"}${run.candidate_count ? `本次新增 ${run.candidate_count} 个待处理术语。` : "本次没有新增术语，可调整发现范围后再试。"}`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在读取发现术语状态…" />;
  if (error && !state) return <ErrorState message={error} retry={() => { setLoading(true); void refresh().catch((reason: unknown) => setError(errorMessage(reason))).finally(() => setLoading(false)); }} />;
  if (!state || !draft) return null;

  const learningDirections = learningContext
    ? [...new Set([
      learningContext.preferences.fixed_direction.trim(),
      ...learningContext.topics.filter((topic) => topic.is_active).map((topic) => topic.title.trim()),
    ].filter(Boolean))]
    : [];
  const latestRun = state.last_run ?? runs[0] ?? null;
  const latestEffectiveFocus = Array.isArray(latestRun?.snapshot.effective_focus)
    ? latestRun.snapshot.effective_focus.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
  const focusMissesLearningDirection = learningContext?.topics.some((topic) =>
    topic.is_active && latestEffectiveFocus.length > 0
    && !latestEffectiveFocus.some((focus) => focus.toLocaleLowerCase().includes(topic.title.toLocaleLowerCase())),
  ) ?? false;

  return (
    <section className="term-discovery-panel" aria-label="发现术语">
      <div className="term-discovery-overview surface">
        <div className="term-discovery-overview-heading">
          <div><span className="section-kicker">发现适合当前学习方向的术语</span><h2>发现术语</h2><p>按学习进度运行和定时发现只分析手动纳入的正式笔记；未选择笔记时不会扫描其他笔记、PDF 或外部摘要。通用发现会读取全库，并可使用已启用的 PDF 与外部来源，需要手动选择。</p></div>
          <div className="term-discovery-actions">
            <button className="button button-primary" type="button" disabled={busy} onClick={() => void runNow("personalized")}>{busy ? "正在运行…" : "按学习进度发现"}</button>
            <button className="button button-secondary" type="button" disabled={busy} onClick={() => void runNow("general")}>{busy ? "正在运行…" : "通用发现（全库）"}</button>
          </div>
        </div>
        <div className="term-discovery-capacity-grid">
          <div><span>待处理术语</span><strong>{state.open_count} / {state.global_capacity}</strong></div>
        </div>
        <section className="term-discovery-direction-summary" aria-label="当前学习方向与最近一次 Terms 实际方向">
          <div><span>当前学习方向</span><strong>{learningDirections.join("、") || "尚未设置明确方向"}</strong></div>
          <div><span>最近一次 Terms 实际方向</span><strong>{latestEffectiveFocus.join("、") || "暂无运行记录"}</strong></div>
          <p>新运行优先使用自定义或固定方向，活跃专题也会参与方向选择；启用的 Research Profiles/Lenses 作为补充。最近一次运行记录用于核对已执行方向。</p>
          {focusMissesLearningDirection && <p className="term-discovery-direction-mismatch" role="status">最近一次运行方向未包含全部活跃专题；活跃方向已变化时，请以新运行记录确认实际范围。</p>}
        </section>
        {state.last_run && <p className="term-discovery-last-run">最近发现 · {RUN_STATUS_LABELS[state.last_run.status]} · {new Date(state.last_run.started_at).toLocaleString()}</p>}
      </div>

      <form className="term-discovery-settings surface" onSubmit={(event) => void saveSettings(event)}>
        <div className="section-heading"><div><h3>发现设置</h3><p>检索主题优先复用研究方向；这里只保存少量运行偏好。</p></div><button className="button button-secondary" type="submit" disabled={busy}>{busy ? "正在保存…" : "保存设置"}</button></div>
        <div className="term-discovery-lanes">
          {LANES.map((lane) => <label className="term-discovery-lane" key={lane.id}>
            <input type="checkbox" checked={draft.enabled_lanes.includes(lane.id)} onChange={() => toggleLane(lane.id)} />
            <span><strong>{lane.title}</strong><small>{lane.description}</small></span>
          </label>)}
        </div>
        <details className="term-discovery-advanced"><summary>高级设置</summary>
        <p>每日还可新增 {state.daily_remaining} 项；定时任务按已纳入的学习资料发现，通用全库扫描需手动选择。</p>
        {LANES.map((lane) => <label className="field-label" key={lane.id}>{lane.title}容量（待处理 {state.lane_open[lane.id] ?? 0}）<input type="number" min={1} max={12} value={draft.lane_capacities[lane.id]} onChange={(event) => setDraft((current) => current ? { ...current, lane_capacities: { ...current.lane_capacities, [lane.id]: Number(event.target.value) } } : current)} aria-label={`${lane.title} capacity`} /></label>)}
        <div className="term-discovery-setting-fields">
          <label className="field-label">每日新增上限<input type="number" min={1} max={12} value={draft.daily_max_new} onChange={(event) => setDraft((current) => current ? { ...current, daily_max_new: Number(event.target.value) } : current)} /></label>
          <label className="field-label">自定义研究方向（可选）<input value={draft.focus_override ?? ""} maxLength={500} onChange={(event) => setDraft((current) => current ? { ...current, focus_override: event.target.value || null } : current)} placeholder="沿用研究方向的方向" /></label>
          <label className="field-label">优先文献标识（逗号分隔）<input value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="例如 source-alpha, source-beta" /></label>
        </div>
        <label className="term-discovery-external-setting">
          <input type="checkbox" checked={draft.external_enabled} onChange={(event) => setDraft((current) => current ? { ...current, external_enabled: event.target.checked } : current)} />
          <span><strong>启用 Wikipedia 外部发现</strong><small>开启后，手动选择通用发现时最多发送一次检索主题查询并读取两条摘要；检索主题查询会发给 Wikipedia，摘要会交给 AI 分析。只用于概念和命名实体。</small></span>
        </label>
        </details>
      </form>

      {notice && <p className="editor-notice success-notice" role="status">{notice}</p>}
      {notice && navigate && <button className="button button-secondary" onClick={() => navigate("/terms?tab=candidates")}>查看待处理术语</button>}
      {error && <p className="error-copy" role="alert">{error}</p>}

      <section className="term-discovery-history surface" aria-label="发现术语发现记录">
        <div className="section-heading"><div><h3>发现记录</h3><p>拓展建议保留在运行结果中，不会占用待处理列表。</p></div><span className="count-label">{runs.length} 次运行</span></div>
        {runs.length ? <div className="term-discovery-run-list">{runs.map((run) => <details className="term-discovery-run" key={run.id}>
          <summary><span><Chip tone={run.status === "success" ? "green" : run.status === "partial" ? "amber" : "neutral"}>{RUN_STATUS_LABELS[run.status]}</Chip><Chip>{run.snapshot.discovery_mode === "general" ? "通用发现" : run.snapshot.discovery_mode === "personalized" ? "学习进度" : "旧版运行"}</Chip> {new Date(run.started_at).toLocaleString()}</span><strong>新增 {run.candidate_count} 个</strong></summary>
          <div className="term-discovery-run-detail">
            <p>预算：概念 {run.lane_budgets.concept ?? 0} · 命名实体 {run.lane_budgets.entity ?? 0} · 专业词汇 {run.lane_budgets.vocabulary ?? 0}</p>
            <p>模型建议 {Object.values(run.raw_counts).reduce((sum, value) => sum + value, 0)} · 过滤 {Object.values(run.filtered_counts).reduce((sum, value) => sum + value, 0)}</p>
            {run.error_summary && <p className="error-copy">{run.error_summary}</p>}
            {run.items.map((item) => <article className="term-discovery-result" key={item.id}>
              <div><strong>{item.mention}</strong><Chip>{LANE_LABELS[item.lane]}</Chip><Chip tone={item.outcome === "created" ? "green" : item.outcome === "stretch" ? "amber" : "neutral"}>{OUTCOME_LABELS[item.outcome]}</Chip><Chip>准备度：{READINESS_LABELS[item.assessment.readiness]}</Chip></div>
              <p>{item.assessment.why_now}</p>
              {(item.assessment.known_prerequisites.length > 0 || item.assessment.missing_prerequisites.length > 0) && <small>已有：{item.assessment.known_prerequisites.join("、") || "—"} · 缺少：{item.assessment.missing_prerequisites.join("、") || "—"}</small>}
              {item.rationale && <blockquote>{item.context_excerpt}</blockquote>}
            </article>)}
          </div>
        </details>)}</div> : <p className="term-discovery-empty">还没有运行记录。选择需要的术语类别后，可手动运行一次。</p>}
      </section>
    </section>
  );
}
