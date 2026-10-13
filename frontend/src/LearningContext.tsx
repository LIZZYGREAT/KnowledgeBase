import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getLearningContext,
  getLearningContextTopic,
  restoreAutomaticLearningContext,
  saveLearningContextMemory,
  saveLearningContextTopic,
  syncLearningContext,
  setLearningContextPreferences,
  setLearningContextSources,
  type LearningContextOverview,
  type LearningContextPreferences,
  type LearningContextTopic,
} from "./api";
import { MarkdownContent } from "./Markdown";
import { EmptyState, ErrorState, PageHeader, SectionHeading } from "./ui";
import type { RegisterBeforeNavigate } from "./navigation";

type MemoryLayer = "active" | "important" | `topic:${string}`;

const preferenceFields: Array<[keyof Omit<LearningContextPreferences, "fixed_direction">, string]> = [
  ["keywords", "搜索关键词"],
  ["exclude_keywords", "排除词"],
  ["exploration_directions", "允许探索的入门方向"],
  ["important_anchors", "重要知识锚点"],
];

function toLines(values: string[]) {
  return values.join("\n");
}

function fromLines(value: string) {
  return Array.from(new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)));
}

function sourceTypeLabel(type: string) {
  if (type === "paper-note") return "论文笔记";
  if (type === "course-note") return "课程笔记（手动选择）";
  return "学习笔记";
}

function memoryPath(layer: MemoryLayer) {
  return layer.startsWith("topic:") ? `topics/${layer.slice(6)}.md` : `${layer}.md`;
}

export function LearningContextPage({ registerBeforeNavigate }: { registerBeforeNavigate?: RegisterBeforeNavigate }) {
  const [overview, setOverview] = useState<LearningContextOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preferencesDraft, setPreferencesDraft] = useState<LearningContextPreferences | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<MemoryLayer>("active");
  const [memoryText, setMemoryText] = useState("");
  const [memoryOriginal, setMemoryOriginal] = useState("");
  const [memoryLoaded, setMemoryLoaded] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryEditing, setMemoryEditing] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const value = await getLearningContext();
      setOverview(value);
      setSelectedIds(value.sources.included_document_ids);
      setPreferencesDraft(value.preferences);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "无法读取学习进度上下文");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const topicId = selectedLayer.startsWith("topic:") ? selectedLayer.slice(6) : "";
  const currentMemory = selectedLayer === "active"
    ? overview?.active ?? ""
    : selectedLayer === "important"
      ? overview?.important ?? ""
      : "";
  const includedIds = overview?.sources.included_document_ids ?? [];
  const sourceDirty = useMemo(
    () => JSON.stringify([...selectedIds].sort()) !== JSON.stringify([...includedIds].sort()),
    [includedIds, selectedIds],
  );
  const preferencesDirty = Boolean(
    overview && preferencesDraft
      && JSON.stringify(preferencesDraft) !== JSON.stringify(overview.preferences),
  );
  const memoryDirty = memoryEditing && memoryLoaded && memoryText !== memoryOriginal;
  const hasUnsavedChanges = sourceDirty || preferencesDirty || memoryDirty;

  useEffect(() => {
    if (!registerBeforeNavigate) return;
    return registerBeforeNavigate(async () => {
      return !hasUnsavedChanges || window.confirm("学习进度有尚未保存的修改，仍要离开吗？");
    });
  }, [hasUnsavedChanges, registerBeforeNavigate]);

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsavedChanges]);

  useEffect(() => {
    let current = true;
    setMemoryLoaded(false);
    setMemoryEditing(false);
    async function loadMemory() {
      setMemoryLoading(true);
      try {
        const text = topicId
          ? (await getLearningContextTopic(topicId)).markdown
          : currentMemory;
        if (current) {
          setMemoryText(text);
          setMemoryOriginal(text);
          setMemoryLoaded(true);
        }
      } catch (error) {
        if (current) setNotice(error instanceof Error ? error.message : "无法读取专题内容");
      } finally {
        if (current) setMemoryLoading(false);
      }
    }
    void loadMemory();
    return () => { current = false; };
  }, [currentMemory, topicId]);

  const visibleSources = useMemo(() => {
    const query = sourceQuery.trim().toLocaleLowerCase();
    const documents = overview?.sources.available_documents ?? [];
    return query
      ? documents.filter((item) => `${item.title} ${item.id} ${item.type}`.toLocaleLowerCase().includes(query))
      : documents;
  }, [overview?.sources.available_documents, sourceQuery]);

  async function saveSources() {
    setSaving(true);
    setNotice("");
    try {
      await setLearningContextSources(selectedIds);
      await refresh();
      setNotice("学习资料范围已保存；内容变化会在同步时处理。未发起模型请求。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存资料范围失败");
    } finally {
      setSaving(false);
    }
  }

  async function savePreferences() {
    if (!preferencesDraft) return;
    setSaving(true);
    setNotice("");
    try {
      await setLearningContextPreferences(preferencesDraft);
      await refresh();
      setNotice("搜索偏好已保存，不会作为已掌握知识。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存搜索偏好失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveMemory() {
    setSaving(true);
    setNotice("");
    try {
      if (topicId) await saveLearningContextTopic(topicId, memoryText);
      else await saveLearningContextMemory(selectedLayer as "active" | "important", memoryText);
      setMemoryEditing(false);
      setMemoryOriginal(memoryText);
      await refresh();
      setNotice("上下文已保存并固定为人工维护内容。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存上下文失败");
    } finally {
      setSaving(false);
    }
  }

  async function restoreAutomatic() {
    setSaving(true);
    setNotice("");
    try {
      await restoreAutomaticLearningContext(topicId ? "topic" : selectedLayer as "active" | "important", topicId || undefined);
      await refresh();
      setMemoryEditing(false);
      setNotice("已恢复自动维护；现有内容已保留，后续同步可更新此层。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "恢复自动维护失败");
    } finally {
      setSaving(false);
    }
  }

  async function runSync(force = false, onlySourceId?: string) {
    if (!overview) return;
    if (sourceDirty || preferencesDirty || memoryDirty) {
      setNotice("请先保存当前未提交的修改，再同步学习上下文。");
      return;
    }
    if (force) {
      const sourceTitle = onlySourceId
        ? overview.sources.available_documents.find((source) => source.id === onlySourceId)?.title ?? onlySourceId
        : `全部已选的 ${sourceCount} 篇笔记`;
      if (!window.confirm(`将重新分析“${sourceTitle}”，并可能发送差异片段给 AI。继续吗？`)) return;
    }
    setSyncing(true);
    setNotice("");
    try {
      const result = await syncLearningContext({ force, source_id: onlySourceId });
      await refresh();
      setNotice(result.message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "同步学习上下文失败");
    } finally {
      setSyncing(false);
    }
  }

  if (loading && !overview) return <div className="page-stack"><PageHeader eyebrow="LEARNING PROGRESS" title="学习进度" /><div className="loading-state" role="status">正在读取学习进度…</div></div>;
  if (loadError && !overview) return <div className="page-stack"><PageHeader eyebrow="LEARNING PROGRESS" title="学习进度" /><ErrorState message={loadError} retry={() => void refresh()} /></div>;
  if (!overview || !preferencesDraft) return null;

  const managedFiles = overview.user_managed_files ?? [];
  const isMemoryManaged = managedFiles.includes(memoryPath(selectedLayer));
  const sourceCount = includedIds.length;
  const topicLayers = overview.topics;
  const statusCopy = overview.status.message ?? (overview.status.state === "synced" ? "已同步" : "尚未同步");

  return (
    <div className="page-stack learning-context-page">
      <PageHeader
        eyebrow="LEARNING PROGRESS"
        title="学习进度"
        description="手动选择哪些正式笔记参与进度判断；在这里查看、整理和编辑推荐所使用的上下文。"
      />

      {notice && <div className="editor-notice success-notice" role="status">{notice}</div>}
      {loadError && <ErrorState message={loadError} retry={() => void refresh()} />}

      <section className="learning-context-status surface" aria-live="polite">
        <div><span className={`learning-status-dot learning-status-${overview.status.state}`} /><strong>{statusCopy}</strong></div>
        <span>{sourceCount ? `已纳入 ${sourceCount} 篇正式笔记` : "尚未选择学习资料"}</span>
        <div className="learning-panel-actions">
          <button className="button button-primary" type="button" disabled={(!sourceCount && overview.status.state !== "pending") || sourceDirty || saving || syncing} onClick={() => void runSync()}>
            {syncing ? "正在检查…" : "同步知识变化"}
          </button>
          <button className="button button-secondary" type="button" disabled={!sourceCount || sourceDirty || saving || syncing} onClick={() => void runSync(true)}>
            重新分析全部已选资料
          </button>
        </div>
      </section>

      <div className="learning-context-management-grid">
        <section className="learning-context-panel surface" aria-labelledby="learning-sources-title">
          <SectionHeading
            title="学习资料范围"
            detail="只使用你明确勾选的正式笔记；课程笔记需要手动选择。"
            action={<span className="chip">已选 {selectedIds.length} 篇</span>}
          />
          <label className="learning-source-search">
            <span className="sr-only">搜索学习资料</span>
            <input value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="搜索笔记标题或 ID" />
          </label>
          <div className="learning-selection-actions">
            <button className="text-button" type="button" onClick={() => setSelectedIds((ids) => Array.from(new Set([...ids, ...visibleSources.map((source) => source.id)])))}>全选当前结果</button>
            <button className="text-button" type="button" onClick={() => setSelectedIds([])}>清空选择</button>
          </div>
          <div className="learning-source-list" aria-label="可选正式笔记">
            {visibleSources.map((source) => (
              <div className="learning-source-option" key={source.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(source.id)}
                    onChange={(event) => setSelectedIds((ids) => event.target.checked
                      ? [...ids, source.id]
                      : ids.filter((item) => item !== source.id))}
                  />
                  <span><strong>{source.title}</strong><small>{sourceTypeLabel(source.type)}</small></span>
                </label>
                {selectedIds.includes(source.id) && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={sourceDirty || saving || syncing}
                    onClick={() => void runSync(true, source.id)}
                  >
                    重新分析这篇
                  </button>
                )}
              </div>
            ))}
            {visibleSources.length === 0 && <EmptyState title="没有可选笔记" description={sourceQuery ? "试试其他搜索词。" : "发布正式学习笔记后，可以在这里手动纳入。"} />}
          </div>
          {overview.sources.missing_document_ids.length > 0 && (
            <p className="learning-missing-sources">有 {overview.sources.missing_document_ids.length} 篇已选笔记已不存在；同步时会撤销其专属上下文。</p>
          )}
          <div className="learning-panel-actions">
            <button className="button button-primary" type="button" disabled={!sourceDirty || saving} onClick={() => void saveSources()}>{saving ? "正在保存…" : "保存资料范围"}</button>
            {sourceDirty && <span className="learning-unsaved">资料范围有未保存的修改</span>}
          </div>
        </section>

        <section className="learning-context-panel surface" aria-labelledby="learning-memory-title">
          <SectionHeading
            title="学习上下文"
            detail="当前关注、重要知识和历史专题分层保存；编辑后该层由你管理。"
          />
          <div className="learning-memory-controls">
            <label className="field-label">
              <span>查看层级</span>
              <select value={selectedLayer} onChange={(event) => setSelectedLayer(event.target.value as MemoryLayer)}>
                <option value="active">当前关注</option>
                <option value="important">重要知识</option>
                {topicLayers.map((topic: LearningContextTopic) => <option value={`topic:${topic.id}`} key={topic.id}>历史专题：{topic.title}</option>)}
              </select>
            </label>
            <span className={`chip ${isMemoryManaged ? "chip-amber" : "chip-green"}`}>{isMemoryManaged ? "人工维护" : "自动维护"}</span>
          </div>
          {memoryLoading ? <div className="loading-state" role="status">正在读取上下文…</div> : (
            <>
              {memoryEditing ? (
                <label className="learning-memory-editor">
                  <span className="sr-only">编辑学习上下文 Markdown</span>
                  <textarea value={memoryText} onChange={(event) => setMemoryText(event.target.value)} spellCheck={false} />
                </label>
              ) : (
                <div className="learning-memory-preview">
                  {memoryText.trim() ? <MarkdownContent content={memoryText} /> : <EmptyState title="这一层还没有内容" description="选择学习资料并同步后会逐步形成上下文；你也可以手动添加自己的说明。" />}
                </div>
              )}
              <div className="learning-panel-actions">
                {memoryEditing ? (
                  <>
                    <button className="button button-primary" type="button" disabled={saving || !memoryDirty} onClick={() => void saveMemory()}>{saving ? "正在保存…" : "保存并固定"}</button>
                    <button className="button button-secondary" type="button" disabled={saving} onClick={() => { setMemoryText(memoryOriginal); setMemoryEditing(false); }}>取消</button>
                    {memoryDirty && <span className="learning-unsaved">上下文有未保存的修改</span>}
                  </>
                ) : (
                  <>
                    <button className="button button-secondary" type="button" onClick={() => { setMemoryText(memoryOriginal); setMemoryEditing(true); }}>编辑这一层</button>
                    {isMemoryManaged && <button className="text-button" type="button" disabled={saving} onClick={() => void restoreAutomatic()}>恢复自动维护</button>}
                  </>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      <section className="learning-context-panel surface" aria-labelledby="learning-preferences-title">
        <SectionHeading title="搜索偏好" detail="这些设置改变搜索方向，不会把任何内容记作已掌握。" />
        <div className="learning-preferences-grid">
          <label className="field-label learning-direction-field">
            <span>固定研究方向</span>
            <input value={preferencesDraft.fixed_direction} maxLength={300} onChange={(event) => setPreferencesDraft({ ...preferencesDraft, fixed_direction: event.target.value })} placeholder="可留空" />
          </label>
          {preferenceFields.map(([key, label]) => (
            <label className="field-label" key={key}>
              <span>{label}<small>每行一项</small></span>
              <textarea
                className="learning-preference-list"
                value={toLines(preferencesDraft[key])}
                onChange={(event) => setPreferencesDraft({ ...preferencesDraft, [key]: fromLines(event.target.value) })}
                placeholder="可留空"
              />
            </label>
          ))}
        </div>
        <div className="learning-panel-actions">
          <button className="button button-primary" type="button" disabled={!preferencesDirty || saving} onClick={() => void savePreferences()}>{saving ? "正在保存…" : "保存搜索偏好"}</button>
          {preferencesDirty && <span className="learning-unsaved">搜索偏好有未保存的修改</span>}
        </div>
      </section>
    </div>
  );
}
