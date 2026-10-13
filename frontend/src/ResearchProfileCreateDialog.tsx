import { useState, type FormEvent } from "react";
import { stringify } from "yaml";
import {
  createDraft,
  type ResearchProfile,
  type ResearchProfileSummary,
} from "./api";
import { errorMessage } from "./errors";

export function ResearchProfileCreateDialog({
  profiles,
  sourceProfile,
  onClose,
  onCreated,
}: {
  profiles: ResearchProfileSummary[];
  sourceProfile: ResearchProfile | null;
  onClose: () => void;
  onCreated: (profile: ResearchProfile, draftContent: string, draftCreatedInThisFlow: boolean) => void;
}) {
  const [id, setId] = useState("");
  const [profileIdManuallyEdited, setProfileIdManuallyEdited] = useState(false);
  const [title, setTitle] = useState(sourceProfile ? `${sourceProfile.title} Copy` : "");
  const [description, setDescription] = useState(sourceProfile?.description ?? "");
  const [lensId, setLensId] = useState("main");
  const [initialQuery, setInitialQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    const normalizedId = profileIdManuallyEdited
      ? id.trim()
      : sourceProfile
        ? uniqueCopyProfileId(sourceProfile.id, profiles)
        : uniqueProfileId(normalizedTitle, profiles);
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(normalizedId)) {
      setError("研究方向 ID 只能使用小写字母、数字和连字符。");
      return;
    }
    if (profiles.some((profile) => profile.id === normalizedId)) {
      setError("该研究方向 ID 已存在，请选择其他 ID。");
      return;
    }
    if (!normalizedTitle) {
      setError("研究方向名称不能为空。");
      return;
    }
    if (!sourceProfile && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(lensId.trim())) {
      setError("初始检索主题 ID 只能使用小写字母、数字和连字符。");
      return;
    }
    if (!sourceProfile && !initialQuery.trim()) {
      setError("初始检索词不能为空。");
      return;
    }
    const profile: ResearchProfile = sourceProfile
      ? { ...sourceProfile, id: normalizedId, title: normalizedTitle, description: description.trim() || null }
      : {
        schema_version: 1,
        id: normalizedId,
        title: normalizedTitle,
        description: description.trim() || null,
        enabled: true,
        lenses: [{
          id: lensId.trim(),
          title: "主要主题",
          enabled: true,
          priority: "medium",
          queries: [initialQuery.trim()],
          include_terms: [],
          exclude_terms: [],
        }],
        exclude_terms: [],
        providers: { discovery: ["arxiv"], enrichment: [] },
        context: { collections: [], documents: [], dynamic_retrieval: { enabled: true, scope: "entire-library" } },
        schedule: { mode: "daily" },
        search: { breadth: "balanced", initial_lookback_days: 30, max_catchup_days: 30, max_candidates_per_run: 10, max_analyses_per_run: 30 },
        inbox: { max_new_candidates: 20 },
        ai_analysis: { enabled: false, provider: "deepseek" },
      };

    setBusy(true);
    setError("");
    try {
      const content = stringify(profile, { lineWidth: 0 });
      const acquired = await createDraft("research_profile", profile.id, content);
      onCreated(profile, acquired.created ? content : acquired.draft.content, acquired.created);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="research-dismiss-dialog research-profile-create-dialog" role="dialog" aria-modal="true" aria-labelledby="research-profile-create-title">
      <header>
        <p className="eyebrow">{sourceProfile ? "复制研究方向" : "新建研究方向"}</p>
        <h2 id="research-profile-create-title">{sourceProfile ? "复制研究方向" : "新建研究方向"}</h2>
        <p>先填写名称和检索主题，再检查设置；确认保存后，研究方向才会进入列表。</p>
      </header>
      <form onSubmit={(event) => void submit(event)}>
        {error && <p className="error-copy" role="alert">{error}</p>}
        {sourceProfile && <label className="field-label">研究方向 ID<input aria-label="新建研究方向 ID" value={profileIdManuallyEdited ? id : uniqueCopyProfileId(sourceProfile.id, profiles)} onChange={(event) => { setId(event.target.value); setProfileIdManuallyEdited(true); }} placeholder="e.g. llm-agents" autoFocus /></label>}
        <label className="field-label">研究方向名称<input aria-label="新建研究方向名称" value={title} onChange={(event) => setTitle(event.target.value)} autoFocus={!sourceProfile} /></label>
        <label className="field-label">描述<textarea aria-label="新建研究方向描述" rows={2} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        {sourceProfile ? <p className="field-hint">复制现有设置；下一步可检查并调整。</p> : <label className="field-label">初始检索词<textarea aria-label="初始检索词" rows={3} value={initialQuery} onChange={(event) => setInitialQuery(event.target.value)} placeholder="例如：regularization continual learning" /></label>}
        {!sourceProfile && <details className="research-advanced-settings">
          <summary>高级标识设置</summary>
          <label className="field-label">研究方向 ID<input aria-label="新建研究方向 ID" value={profileIdManuallyEdited ? id : uniqueProfileId(title, profiles)} onChange={(event) => { setId(event.target.value); setProfileIdManuallyEdited(true); }} placeholder="e.g. llm-agents" /><span className="field-hint">默认根据名称生成；重名时自动追加序号。</span></label>
          <label className="field-label">初始检索主题 ID<input aria-label="初始检索主题 ID" value={lensId} onChange={(event) => setLensId(event.target.value)} /></label>
        </details>}
        <footer className="research-dialog-actions">
          <button className="button button-quiet" type="button" disabled={busy} onClick={onClose}>取消</button>
          <button className="button button-primary" type="submit" disabled={busy}>{busy ? "正在创建研究方向…" : "创建研究方向"}</button>
        </footer>
      </form>
    </section>
  </div>;
}

function uniqueProfileId(title: string, profiles: ResearchProfileSummary[]) {
  const base = title.trim().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "research-profile";
  return uniqueId(base, profiles);
}

function uniqueCopyProfileId(sourceId: string, profiles: ResearchProfileSummary[]) {
  return uniqueId(`${sourceId}-copy`, profiles);
}

function uniqueId(base: string, profiles: ResearchProfileSummary[]) {
  const usedIds = new Set(profiles.map((profile) => profile.id));
  if (!usedIds.has(base)) return base;
  let suffix = 2;
  while (usedIds.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}
