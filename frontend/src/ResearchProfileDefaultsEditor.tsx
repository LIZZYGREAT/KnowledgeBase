import { useEffect, useMemo, useState } from "react";
import { parse, parseDocument } from "yaml";
import {
  compareDraft,
  listAllEntities,
  listCollections,
  preflightDraft,
  publishDraft,
  reviewResearchReactivation,
  type CollectionSummary,
  type DraftComparison,
  type DraftPreflight,
  type EntitySummary,
  type ResearchBreadth,
  type ResearchProfile,
  type ResearchReactivationReview,
  type ResearchReactivationStrategy,
} from "./api";
import { useRuntimeDraftSession } from "./draft/useRuntimeDraftSession";
import { errorMessage } from "./errors";
import { createLineDiff } from "./publishReview";

interface ResearchProfileDefaultsEditorProps {
  profile: ResearchProfile;
  canonicalContent: string;
  onClose: () => void;
  onPublished: (warnings: string[]) => void;
}

interface ProfileReview {
  comparison: DraftComparison;
  preflight: DraftPreflight;
  reactivation: ResearchReactivationReview | null;
}

export function ResearchProfileDefaultsEditor({ profile, canonicalContent, onClose, onPublished }: ResearchProfileDefaultsEditorProps) {
  const initialContent = useMemo(() => canonicalContent, [canonicalContent]);
  const session = useRuntimeDraftSession({
    entityType: "research_profile",
    entityId: profile.id,
    enabled: true,
    initialContent,
    initialContentReady: true,
  });
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [documents, setDocuments] = useState<EntitySummary[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [libraryError, setLibraryError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [review, setReview] = useState<ProfileReview | null>(null);
  const [reactivationStrategy, setReactivationStrategy] = useState<ResearchReactivationStrategy | "">("");

  useEffect(() => {
    let active = true;
    setLibraryLoading(true);
    void Promise.all([listCollections("active"), listAllEntities("document")])
      .then(([nextCollections, nextDocuments]) => {
        if (!active) return;
        setCollections(nextCollections);
        setDocuments(nextDocuments);
        setLibraryError("");
      })
      .catch((reason: unknown) => {
        if (active) setLibraryError(errorMessage(reason));
      })
      .finally(() => {
        if (active) setLibraryLoading(false);
      });
    return () => { active = false; };
  }, []);

  let editableProfile: ResearchProfile | null = null;
  let parseError = "";
  if (session.content) {
    try {
      const value: unknown = parse(session.content);
      if (!isRecord(value) || value.id !== profile.id || !Array.isArray(value.lenses)) {
        throw new Error("Draft 的 Profile ID 或 Lens 结构无效。");
      }
      editableProfile = value as unknown as ResearchProfile;
    } catch (reason) {
      parseError = errorMessage(reason);
    }
  }

  function updateProfile(transform: (current: ResearchProfile) => ResearchProfile) {
    if (!editableProfile) return;
    setReview(null);
    setReactivationStrategy("");
    setError("");
    setNotice("");
    const document = parseDocument(session.content);
    const currentValue = document.toJS();
    const nextValue = transform(editableProfile);
    applyYamlDiff(document, [], currentValue, nextValue);
    session.updateContent(document.toString({ lineWidth: 0 }));
  }

  async function closeEditor() {
    if (busy) return;
    if (session.isDirty) {
      setBusy(true);
      setError("");
      try {
        await session.saveNow();
        onClose();
      } catch (reason) {
        setError(errorMessage(reason));
      } finally {
        setBusy(false);
      }
      return;
    }
    onClose();
  }

  async function reviewChanges() {
    setBusy(true);
    setError("");
    setNotice("");
    setReview(null);
    try {
      const saved = await session.saveNow();
      if (!saved) {
        setNotice("Defaults 没有变化，无需发布。");
        return;
      }
      const [comparison, preflight] = await Promise.all([
        compareDraft(saved.id),
        preflightDraft(saved.id),
      ]);
      const reactivation = preflight.valid
        ? await reviewResearchReactivation(profile.id, saved.id)
        : null;
      setReactivationStrategy("");
      setReview({ comparison, preflight, reactivation });
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function publishChanges() {
    if (!review || !session.draft || review.comparison.canonical_changed || !review.preflight.valid) return;
    const strategy = review.reactivation?.required
      ? reactivationStrategy || undefined
      : undefined;
    if (review.reactivation?.required && !strategy) return;
    setBusy(true);
    setError("");
    try {
      const published = await publishDraft(
        session.draft.id,
        session.draft.revision,
        strategy,
      );
      onPublished(published.warnings);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  const statusText = session.state === "loading" ? "正在读取 Draft…"
    : session.state === "saving" ? "正在自动保存…"
      : session.state === "unsaved" || session.isDirty ? "有未保存修改"
        : session.draft ? "Draft 已保存"
          : "与已发布 Defaults 一致";
  const canReview = Boolean(editableProfile)
    && session.state !== "loading"
    && session.state !== "saving"
    && session.state !== "error"
    && session.state !== "runtime-conflict";
  const diffLines = review
    ? createLineDiff(review.comparison.current_content, review.comparison.draft.content)
    : [];

  return <div className="research-modal-overlay research-profile-editor-overlay" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) void closeEditor();
  }}>
    <section className="research-dismiss-dialog research-profile-editor" role="dialog" aria-modal="true" aria-labelledby="research-profile-editor-title">
      <header className="research-profile-editor-header">
        <div><p className="eyebrow">PROFILE DEFAULTS</p><h2 id="research-profile-editor-title">编辑 {profile.title}</h2><p>修改会先自动保存为 Draft；检查差异并通过校验后，才会写入 canonical Profile。</p></div>
        <button className="button button-quiet" type="button" disabled={busy} onClick={() => void closeEditor()}>关闭</button>
      </header>
      <div className="research-profile-editor-body">
        <div className="research-profile-draft-status" role="status"><strong>{statusText}</strong><span>Research Profile Draft · {profile.id}</span></div>
        {session.error && <p className="error-copy" role="alert">{session.error}</p>}
        {error && <p className="error-copy" role="alert">{error}</p>}
        {notice && <p className="notice" role="status">{notice}</p>}
        {parseError && <p className="error-copy" role="alert">无法读取 Profile Draft：{parseError}</p>}
        {libraryError && <p className="error-copy" role="alert">读取 Context 选项失败：{libraryError}</p>}

        {editableProfile && <>
          <section className="research-defaults-section">
            <div className="research-section-heading"><div><h3>Search lenses</h3><p>启用状态、优先级和查询词将作为后续搜索默认值。</p></div></div>
            {editableProfile.lenses.map((lens, index) => <article className="research-default-lens" key={lens.id}>
              <div className="research-default-lens-heading"><label><input type="checkbox" checked={lens.enabled} onChange={(event) => updateProfile((current) => updateLens(current, index, { enabled: event.target.checked }))} /><span><strong>{lens.title}</strong><small>{lens.id}</small></span></label><label className="field-label">优先级<select value={lens.priority} onChange={(event) => updateProfile((current) => updateLens(current, index, { priority: event.target.value as typeof lens.priority }))}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label></div>
              <div className="research-defaults-grid">
                <TextListField label="Queries" value={lens.queries} onChange={(value) => updateProfile((current) => updateLens(current, index, { queries: value }))} />
                <TextListField label="Include terms" value={lens.include_terms} onChange={(value) => updateProfile((current) => updateLens(current, index, { include_terms: value }))} />
                <TextListField label="Lens exclude terms" value={lens.exclude_terms} onChange={(value) => updateProfile((current) => updateLens(current, index, { exclude_terms: value }))} />
              </div>
            </article>)}
            <TextListField label="Profile exclude terms" value={editableProfile.exclude_terms} onChange={(value) => updateProfile((current) => ({ ...current, exclude_terms: value }))} />
          </section>

          <section className="research-defaults-section">
            <div className="research-section-heading"><div><h3>Search defaults</h3><p>这些值用于后续运行；单次 Search Now 可以另行覆盖 breadth 和日期。</p></div></div>
            <div className="research-defaults-grid research-defaults-fields">
              <label className="research-default-toggle"><input type="checkbox" checked={editableProfile.enabled} onChange={(event) => updateProfile((current) => ({ ...current, enabled: event.target.checked }))} /><span>Enable Research Profile</span></label>
              <label className="field-label">Default breadth<select value={editableProfile.search.breadth} onChange={(event) => updateProfile((current) => ({ ...current, search: { ...current.search, breadth: event.target.value as ResearchBreadth } }))}><option value="strict">Strict · 高相关</option><option value="balanced">Balanced · 均衡</option><option value="explore">Explore · 新颖性</option></select></label>
              <label className="field-label">Schedule<select value={editableProfile.schedule.mode} onChange={(event) => updateProfile((current) => ({ ...current, schedule: { mode: event.target.value as ResearchProfile["schedule"]["mode"] } }))}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="manual">Manual only</option></select></label>
              <NumberField label="Initial lookback days" value={editableProfile.search.initial_lookback_days} min={1} onChange={(value) => updateProfile((current) => ({ ...current, search: { ...current.search, initial_lookback_days: value } }))} />
              <NumberField label="Max catch-up days" value={editableProfile.search.max_catchup_days} min={1} onChange={(value) => updateProfile((current) => ({ ...current, search: { ...current.search, max_catchup_days: value } }))} />
              <NumberField label="Max candidates per run" value={editableProfile.search.max_candidates_per_run} min={1} onChange={(value) => updateProfile((current) => ({ ...current, search: { ...current.search, max_candidates_per_run: value } }))} />
              <NumberField label="Max analyses per run" value={editableProfile.search.max_analyses_per_run} min={1} onChange={(value) => updateProfile((current) => ({ ...current, search: { ...current.search, max_analyses_per_run: value } }))} />
              <NumberField label="Inbox max new candidates" value={editableProfile.inbox.max_new_candidates} min={0} onChange={(value) => updateProfile((current) => ({ ...current, inbox: { max_new_candidates: value } }))} />
            </div>
          </section>

          <section className="research-defaults-section">
            <div className="research-section-heading"><div><h3>Knowledge context</h3><p>选择固定引用，并配置动态检索默认值。</p></div></div>
            {libraryLoading ? <p className="field-hint">正在载入 Collections 和 Documents…</p> : <div className="research-defaults-context-grid">
              <SelectionList label="Pinned Collections" items={collections.map((item) => ({ id: item.id, title: item.title }))} selected={editableProfile.context.collections} onChange={(value) => updateProfile((current) => ({ ...current, context: { ...current.context, collections: value } }))} />
              <SelectionList label="Pinned Documents" items={documents.map((item) => ({ id: item.id, title: item.title }))} selected={editableProfile.context.documents} onChange={(value) => updateProfile((current) => ({ ...current, context: { ...current.context, documents: value } }))} />
            </div>}
            <div className="research-defaults-grid research-defaults-fields">
              <label className="research-default-toggle"><input type="checkbox" checked={editableProfile.context.dynamic_retrieval.enabled} onChange={(event) => updateProfile((current) => ({ ...current, context: { ...current.context, dynamic_retrieval: { ...current.context.dynamic_retrieval, enabled: event.target.checked } } }))} /><span>Enable dynamic retrieval</span></label>
              <label className="field-label">Dynamic Retrieval scope<select aria-label="Dynamic Retrieval scope" value={editableProfile.context.dynamic_retrieval.scope} onChange={(event) => updateProfile((current) => ({ ...current, context: { ...current.context, dynamic_retrieval: { ...current.context.dynamic_retrieval, scope: event.target.value as ResearchProfile["context"]["dynamic_retrieval"]["scope"] } } }))}><option value="entire-library">Entire library</option><option value="selected-context">Selected Collections and Documents</option></select><span className="field-hint">Selected context limits retrieved and analyzed material to pinned Documents and Collection members.</span></label>
              <label className="research-default-toggle"><input type="checkbox" checked={editableProfile.ai_analysis.enabled} onChange={(event) => updateProfile((current) => ({ ...current, ai_analysis: { ...current.ai_analysis, enabled: event.target.checked } }))} /><span>AI Analysis enabled</span></label>
            </div>
          </section>
        </>}

        {review && <section className="research-default-review" aria-label="Profile Draft review">
          <div className="research-section-heading"><div><h3>Review Draft diff</h3><p>左侧移除的是当前 canonical 内容，右侧新增的是待发布 Draft。</p></div><button className="button button-quiet" type="button" disabled={busy} onClick={() => { setReview(null); setReactivationStrategy(""); }}>返回编辑</button></div>
          {review.comparison.canonical_changed && <p className="error-copy" role="alert">Canonical Profile 在 Draft 创建后已变化。请关闭并重新载入后再编辑。</p>}
          <div className="research-profile-diff" role="region" aria-label="Profile changes">{diffLines.map((line, index) => <div className={`research-profile-diff-line ${line.kind}`} key={`${index}-${line.kind}`}><span>{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span><code>{line.text || " "}</code></div>)}</div>
          <div className="research-profile-preflight" aria-live="polite">
            {review.preflight.valid ? <p className="notice">Profile Draft preflight 通过。</p> : <ul className="error-copy">{review.preflight.errors.map((item) => <li key={item}>{item}</li>)}</ul>}
            {review.preflight.warnings.map((item) => <p className="field-hint" key={item}>{item}</p>)}
          </div>
          {review.reactivation?.required && <fieldset className="research-profile-reactivation" aria-label="Reactivation Review">
            <legend>Reactivation Review</legend>
            <p>这些设置将恢复自动发现，当前水位线已超过追赶上限。请选择本次如何处理旧水位线。</p>
            <ul>{review.reactivation.triggers.map((trigger) => <li key={trigger}>{reactivationTriggerLabel(trigger)}</li>)}</ul>
            <label><input type="radio" name="reactivation-strategy" value="last_window" checked={reactivationStrategy === "last_window"} onChange={() => setReactivationStrategy("last_window")} />Catch up last {review.reactivation.max_catchup_days} days</label>
            <label><input type="radio" name="reactivation-strategy" value="all" checked={reactivationStrategy === "all"} onChange={() => setReactivationStrategy("all")} />Catch up all</label>
            <label><input type="radio" name="reactivation-strategy" value="from_now" checked={reactivationStrategy === "from_now"} onChange={() => setReactivationStrategy("from_now")} />Start from now</label>
          </fieldset>}
        </section>}
      </div>
      <footer className="research-dialog-actions research-profile-editor-footer">
        {review ? <button className="button button-primary" type="button" disabled={busy || !review.preflight.valid || review.comparison.canonical_changed || Boolean(review.reactivation?.required && !reactivationStrategy)} onClick={() => void publishChanges()}>{busy ? "正在发布…" : "Publish Defaults"}</button>
          : <button className="button button-primary" type="button" disabled={!canReview || busy || (!session.draft && !session.isDirty)} onClick={() => void reviewChanges()}>{busy ? "正在保存并审查…" : "Review Diff"}</button>}
        <span>发布通过 Publisher 校验，并提交到 Git。</span>
      </footer>
    </section>
  </div>;
}

function TextListField({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  return <label className="field-label research-default-list-field">{label}<span className="field-hint">每行一项</span><textarea rows={3} value={value.join("\n")} onChange={(event) => onChange(parseLines(event.target.value))} /></label>;
}

function NumberField({ label, value, min, onChange }: { label: string; value: number; min: number; onChange: (value: number) => void }) {
  return <label className="field-label">{label}<input type="number" min={min} step={1} value={value} onChange={(event) => onChange(event.target.value === "" ? min - 1 : Number(event.target.value))} /></label>;
}

function SelectionList({ label, items, selected, onChange }: { label: string; items: Array<{ id: string; title: string }>; selected: string[]; onChange: (selected: string[]) => void }) {
  return <fieldset className="research-default-selection"><legend>{label}</legend>{items.length ? items.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(event) => onChange(event.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} /><span>{item.title}</span></label>) : <p className="field-hint">没有可选项。</p>}</fieldset>;
}

function updateLens(profile: ResearchProfile, index: number, patch: Partial<ResearchProfile["lenses"][number]>): ResearchProfile {
  return { ...profile, lenses: profile.lenses.map((lens, lensIndex) => lensIndex === index ? { ...lens, ...patch } : lens) };
}

function applyYamlDiff(document: ReturnType<typeof parseDocument>, path: Array<string | number>, current: unknown, next: unknown) {
  if (Object.is(current, next)) return;
  if (Array.isArray(current) && Array.isArray(next)) {
    const sharedLength = Math.min(current.length, next.length);
    for (let index = 0; index < sharedLength; index += 1) {
      applyYamlDiff(document, [...path, index], current[index], next[index]);
    }
    for (let index = current.length - 1; index >= next.length; index -= 1) {
      document.deleteIn([...path, index]);
    }
    for (let index = current.length; index < next.length; index += 1) {
      document.addIn(path, next[index]);
    }
    return;
  }
  if (isRecord(current) && isRecord(next)) {
    for (const key of Object.keys(current)) {
      if (!(key in next)) document.deleteIn([...path, key]);
    }
    for (const [key, value] of Object.entries(next)) {
      if (key in current) applyYamlDiff(document, [...path, key], current[key], value);
      else document.setIn([...path, key], value);
    }
    return;
  }
  document.setIn(path, next);
}

function parseLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function reactivationTriggerLabel(trigger: string): string {
  if (trigger === "profile_enabled") return "启用 Research Profile";
  if (trigger === "ai_analysis_enabled") return "启用 AI Analysis";
  if (trigger === "schedule_enabled") return "将 Schedule 从 Manual 改为自动运行";
  if (trigger.startsWith("lens_enabled:")) return `启用 Lens：${trigger.slice("lens_enabled:".length)}`;
  return trigger;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
