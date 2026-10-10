import { useEffect, useState, type FormEvent } from "react";
import {
  pauseResearchProfile,
  queueResearchRun,
  resumeResearchProfile,
  type QueueResearchRunInput,
  type ResearchBreadth,
  type ResearchProfileDetail,
  type ResearchProfileSummary,
} from "./api";
import { Chip, formatDate } from "./ui";
import { errorMessage } from "./errors";

function localDateInputValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDateBoundary(value: string, dayOffset = 0) {
  const [year, month, day] = value.split("-").map(Number);
  const boundary = new Date(0);
  boundary.setFullYear(year, month - 1, day + dayOffset);
  boundary.setHours(0, 0, 0, 0);
  return boundary;
}

function isValidLocalDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    && localDateInputValue(localDateBoundary(value)) === value;
}

export function ResearchProfilePanel({
  summary,
  detail,
  onRefresh,
  onQueued,
  onEditDefaults,
}: {
  summary: ResearchProfileSummary;
  detail: ResearchProfileDetail;
  onRefresh: () => void;
  onQueued: () => void;
  onEditDefaults: () => void;
}) {
  const profile = detail.profile;
  const hasActiveDefaultLens = profile.lenses.some((lens) => lens.enabled);
  const pausedUntil = detail.runtime_state?.paused_until ?? null;
  const isPaused = Boolean(pausedUntil && new Date(pausedUntil).getTime() > Date.now());
  const canSearch = summary.enabled
    && (!profile.ai_analysis.enabled || summary.inbox.remaining > 0);
  const [pauseOpen, setPauseOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [pauseUntil, setPauseUntil] = useState("");
  const [resumeStrategy, setResumeStrategy] = useState<"catch_up" | "from_now">("catch_up");
  const [catchupDays, setCatchupDays] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedLenses, setSelectedLenses] = useState<string[]>([]);
  const [additionalQueryLens, setAdditionalQueryLens] = useState("");
  const [breadth, setBreadth] = useState<ResearchBreadth>(profile.search.breadth);
  const [dateMode, setDateMode] = useState<QueueResearchRunInput["date_range"] extends infer T ? T extends { mode: infer M } ? M : never : never>("last_30_days");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [queries, setQueries] = useState("");

  useEffect(() => {
    setSelectedLenses(profile.lenses.filter((lens) => lens.enabled).map((lens) => lens.id));
    setBreadth(profile.search.breadth);
    setQueries("");
    setAdditionalQueryLens("");
    setDateMode("last_30_days");
  }, [profile.id, profile.search.breadth, profile.lenses]);

  useEffect(() => {
    if (additionalQueryLens && !selectedLenses.includes(additionalQueryLens)) {
      setAdditionalQueryLens("");
    }
  }, [additionalQueryLens, selectedLenses]);

  async function pause(days: number) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await pauseResearchProfile(profile.id, { days });
      setPauseOpen(false);
      setNotice(`Research 已暂停 ${days} 天。`);
      onRefresh();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function pauseToDate() {
    if (!pauseUntil) return;
    const localEndOfDay = new Date(`${pauseUntil}T23:59:00`);
    if (Number.isNaN(localEndOfDay.getTime())) {
      setError("请选择有效日期。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await pauseResearchProfile(profile.id, { until: localEndOfDay.toISOString() });
      setPauseOpen(false);
      setNotice(`Research 将暂停至 ${formatDate(localEndOfDay.toISOString())}。`);
      onRefresh();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    setBusy(true);
    setError("");
    try {
      await resumeResearchProfile(profile.id, {
        strategy: resumeStrategy,
        ...(resumeStrategy === "catch_up" && catchupDays ? { catchup_days: Number(catchupDays) } : {}),
      });
      setNotice(resumeStrategy === "from_now" ? "已恢复；暂停期间的搜索窗口已跳过。" : "已恢复；将按追赶策略继续搜索。");
      onRefresh();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!selectedLenses.length) {
      setError("至少选择一个 Research Focus。");
      return;
    }
    if (dateMode === "custom" && (!dateStart || !dateEnd)) {
      setError("自定义时间范围需要开始和结束日期。");
      return;
    }
    if (dateMode === "custom" && (!isValidLocalDate(dateStart) || !isValidLocalDate(dateEnd))) {
      setError("请选择有效日期。");
      return;
    }
    if (dateMode === "custom" && dateStart > dateEnd) {
      setError("结束日期不能早于开始日期。");
      return;
    }
    if (dateMode === "custom" && dateEnd > localDateInputValue(new Date())) {
      setError("结束日期不能晚于今天。");
      return;
    }
    let dateRange: QueueResearchRunInput["date_range"];
    if (dateMode === "custom") {
      const customStart = localDateBoundary(dateStart);
      const customEnd = localDateBoundary(dateEnd, 1);
      dateRange = {
        mode: "custom",
        start: customStart.toISOString(),
        end: new Date(Math.min(customEnd.getTime(), Date.now())).toISOString(),
      };
    } else {
      dateRange = { mode: dateMode };
    }
    const queryLines = queries.split(/\r?\n/).map((query) => query.trim()).filter(Boolean);
    const normalizedQueries = new Set(queryLines.map((query) => query.toLowerCase().replace(/\s+/g, " ")));
    if (queryLines.length > 20 || queryLines.some((query) => query.length > 2_000) || normalizedQueries.size !== queryLines.length) {
      setError("额外检索词需要唯一，每条最多 2,000 字符，最多 20 条。");
      return;
    }
    const priority = { low: 0, medium: 1, high: 2 };
    const additionalQueryTarget = selectedLenses.length === 1
      ? selectedLenses[0]
      : additionalQueryLens || profile.lenses
        .filter((lens) => selectedLenses.includes(lens.id))
        .sort((left, right) => priority[right.priority] - priority[left.priority])[0]?.id;
    setBusy(true);
    setNotice("");
    const input: QueueResearchRunInput = {
      lenses: selectedLenses,
      breadth,
      date_range: dateRange,
      additional_queries: queryLines,
      ...(queryLines.length && additionalQueryTarget ? { additional_query_lens: additionalQueryTarget } : {}),
    };
    try {
      await queueResearchRun(profile.id, input);
      onQueued();
      setSearchOpen(false);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  function toggleLens(id: string) {
    setSelectedLenses((current) => {
      return current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
    });
  }

  const scheduledText = !hasActiveDefaultLens ? "No active default Focus · 自动发现当前不会执行" : profile.schedule.mode === "manual" ? "仅手动搜索" : profile.schedule.mode === "daily" ? "每日由调度器检查" : "每周由调度器检查";
  const capacityPercent = summary.inbox.capacity === 0 ? 100 : Math.min(100, summary.inbox.new_count / summary.inbox.capacity * 100);

  return <section className="surface research-profile-panel">
    <div className="research-profile-heading">
      <div>
        <div className="research-status-line">
          <Chip tone={isPaused ? "amber" : summary.enabled ? "green" : "rose"}>{isPaused ? "Auto paused" : summary.enabled ? "Active" : "Disabled"}</Chip>
          {!profile.ai_analysis.enabled && <Chip tone="amber">DeepSeek analysis off</Chip>}
          <span>{scheduledText}</span>
        </div>
        <h2>{profile.title}</h2>
        <p>{profile.description || "Research Profile 的外部发现与知识关联。"}</p>
        <p>{(detail.history_anchor_year ?? profile.search.history_seed_year) != null
          ? `历史研究起点：${detail.history_anchor_year ?? profile.search.history_seed_year} 年；按年度窗口逐步探索。`
          : "缺少研究阶段锚点，当前仅进行近期发现。请设置起始年份，或在笔记元数据中人工批准有来源年份的已掌握内容。"} <button className="text-button" onClick={onEditDefaults}>设置研究起点</button></p>
        <small>{detail.latest_run ? `最近运行 ${formatDate(detail.latest_run.started_at)} · ${detail.latest_run.status}` : "尚无运行记录"}</small>
      </div>
      <div className="research-profile-actions">
        <button className="button button-secondary" type="button" onClick={onEditDefaults}>Edit Defaults</button>
        {!isPaused && <button className="button button-secondary" disabled={busy || !summary.enabled} onClick={() => setPauseOpen((open) => !open)}>Pause automatic research</button>}
        <button className="button button-primary" disabled={!canSearch} onClick={() => setSearchOpen((open) => !open)}>{searchOpen ? "Close Search" : "Search Now"}</button>
      </div>
    </div>

    {!summary.enabled && <p className="research-search-block-note" role="status">Profile disabled · 启用 Profile 后才能运行 Search Now。</p>}
    {isPaused && <p className="research-search-block-note" role="status">自动检索已暂停至 {formatDate(pausedUntil)}。手动搜索仍可使用。</p>}
    {!profile.ai_analysis.enabled && <p className="research-search-block-note" role="status">AI 分析已关闭。系统仍会收集论文，但不会向 DeepSeek 发送论文或知识库内容，也不会生成推荐候选。重新开启后，系统会逐步处理之前收集但尚未分析的论文。</p>}
    {!hasActiveDefaultLens && <p className="research-search-block-note" role="status">Search Now 仍可临时选择 Research Focus。</p>}

    {isPaused && <section className="research-resume-bar" aria-labelledby="research-resume-heading">
      <h3 id="research-resume-heading">恢复 Research</h3>
      <div className="research-resume-content">
        <label className="field-label research-resume-mode">恢复方式<select value={resumeStrategy} onChange={(event) => setResumeStrategy(event.target.value as typeof resumeStrategy)}><option value="catch_up">追赶暂停期间的内容</option><option value="from_now">从现在开始，不补历史</option></select></label>
        <p className="research-resume-copy">{resumeStrategy === "catch_up"
          ? `从暂停前尚未完成的 scheduled watermark 继续搜索，补查暂停期间遗漏的时间窗；最多回看 ${catchupDays || profile.search.max_catchup_days} 天。`
          : "把 scheduled watermark 推进到现在，跳过暂停期间遗漏的时间窗，只搜索现在之后的新内容。"}</p>
      </div>
      <div className="research-resume-footer">
        {resumeStrategy === "catch_up" && <details className="research-advanced-settings research-resume-advanced"><summary>高级选项</summary><label className="field-label">自定义追赶天数<input aria-label="自定义追赶天数" type="number" min="1" max="3650" value={catchupDays} onChange={(event) => setCatchupDays(event.target.value)} /><span className="field-hint">留空时使用 Profile 配置的 {profile.search.max_catchup_days} 天。</span></label></details>}
        <button className="button button-primary" disabled={busy} onClick={() => void resume()}>Resume Research</button>
      </div>
    </section>}

    {pauseOpen && <div className="research-pause-options">
      <strong>Pause automatic research</strong>
      <div className="research-inline-actions">
        {[1, 3, 7].map((days) => <button className="button button-secondary" key={days} disabled={busy} onClick={() => void pause(days)}>{days} 天</button>)}
      </div>
      <div className="research-pause-date"><label className="field-label">暂停至指定日期<input type="date" value={pauseUntil} min={localDateInputValue(new Date())} onChange={(event) => setPauseUntil(event.target.value)} /></label><button className="button button-secondary" disabled={busy || !pauseUntil} onClick={() => void pauseToDate()}>确认日期</button></div>
    </div>}

    <div className="research-inbox-meter">
      <div className="research-meter-copy"><div><strong>Inbox</strong><span>{summary.inbox.new_count} / {summary.inbox.capacity}</span></div><small>{summary.inbox.remaining} 个新候选名额</small></div>
      <div className="research-meter-track" role="progressbar" aria-label="Inbox 使用量" aria-valuemin={0} aria-valuemax={summary.inbox.capacity} aria-valuenow={summary.inbox.new_count}><span style={{ width: `${capacityPercent}%` }} /></div>
      {summary.inbox.remaining === 0 && profile.ai_analysis.enabled && <p className="research-capacity-note" role="status"><strong>Inbox Full</strong> · 处理候选后才能运行 Search Now。</p>}
    </div>
    {(summary.manual_queue.pending > 0 || summary.manual_queue.claimed > 0) && <p className="research-search-block-note" role="status">
      {summary.manual_queue.pending > 0 && `${summary.manual_queue.pending} manual ${summary.manual_queue.pending === 1 ? "search" : "searches"} queued`}
      {summary.manual_queue.pending > 0 && summary.manual_queue.claimed > 0 && " · "}
      {summary.manual_queue.claimed > 0 && `${summary.manual_queue.claimed} Research ${summary.manual_queue.claimed === 1 ? "request" : "requests"} running`}
    </p>}

    {searchOpen && canSearch && <form className="research-search-form" onSubmit={(event) => void submitSearch(event)}>
      <div className="research-section-heading"><div><h3>Research Focus</h3><p>选择本次搜索的主题和时间范围；这些设置不会修改 Profile 默认值。</p></div></div>
      <div className="research-lens-options">{profile.lenses.map((lens) => <label className="research-lens-option" key={lens.id}><input type="checkbox" checked={selectedLenses.includes(lens.id)} onChange={() => toggleLens(lens.id)} /><span><strong>{lens.title}</strong></span></label>)}</div>
      <div className="research-search-controls">
        <label className="field-label">时间范围<select value={dateMode === "incremental" ? "last_30_days" : dateMode} onChange={(event) => setDateMode(event.target.value as typeof dateMode)}><option value="last_7_days">最近 7 天</option><option value="last_30_days">最近 30 天</option><option value="last_90_days">最近 90 天</option><option value="custom">自定义</option></select></label>
      </div>
      {dateMode === "incremental" && <p className="field-hint research-incremental-help">从自动检索尚未覆盖的位置继续查到现在。这次手动搜索不会改变自动检索的进度。</p>}
      {dateMode === "custom" && <><div className="research-search-controls"><label className="field-label">开始日期<input type="date" max={localDateInputValue(new Date())} value={dateStart} onChange={(event) => setDateStart(event.target.value)} /></label><label className="field-label">结束日期<input type="date" max={localDateInputValue(new Date())} value={dateEnd} onChange={(event) => setDateEnd(event.target.value)} /></label></div><p className="field-hint">结束日期按本地日历包含整天；选择今天时截至当前时刻。</p></>}
      <label className="field-label">额外检索词 <span className="field-hint">每行一条，最多 20 条</span><textarea rows={3} maxLength={40000} value={queries} onChange={(event) => setQueries(event.target.value)} placeholder="dynamic fisher continual learning" /></label>
      <details className="research-advanced-settings">
        <summary>高级搜索选项</summary>
        <label className="field-label">相关性范围<select aria-label="相关性范围" value={breadth} onChange={(event) => setBreadth(event.target.value as ResearchBreadth)}><option value="strict">Strict · 高相关</option><option value="balanced">Balanced · 均衡</option><option value="explore">Explore · 强调新颖性</option></select></label>
        <label className="research-default-toggle"><input type="checkbox" checked={dateMode === "incremental"} onChange={(event) => setDateMode(event.target.checked ? "incremental" : "last_30_days")} /><span>从上次自动检索进度继续</span></label>
        {queries.split(/\r?\n/).some((query) => query.trim()) && selectedLenses.length > 1 && <label className="field-label">额外检索词应用到<select aria-label="额外检索词应用到" value={additionalQueryLens} onChange={(event) => setAdditionalQueryLens(event.target.value)}><option value="">自动选择优先级最高的 Research Focus</option>{profile.lenses.filter((lens) => selectedLenses.includes(lens.id)).map((lens) => <option key={lens.id} value={lens.id}>{lens.title} · {lens.priority}</option>)}</select><span className="field-hint">默认使用本次所选 Research Focus 中优先级最高的一项，并沿用该主题的筛选规则。</span></label>}
      </details>
      {error && <p className="error-copy" role="alert">{error}</p>}
      <div className="research-search-footer"><span>搜索会在后台排队执行，完成后结果会出现在 Inbox。</span><button className="button button-primary" disabled={busy || !selectedLenses.length}>{busy ? "正在排队…" : "加入搜索队列"}</button></div>
    </form>}
    {error && !searchOpen && <p className="error-copy research-inline-error" role="alert">{error}</p>}
    {notice && <p className="notice research-inline-notice" role="status">{notice}</p>}
  </section>;
}
