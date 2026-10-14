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
  setLearningContextTopicStatus,
  updateLearningContextEntry,
  type LearningContextEditableEntry,
  type LearningContextOverview,
  type LearningContextPreferences,
  type LearningContextTopic,
} from "./api";
import { MarkdownContent } from "./Markdown";
import { EmptyState, ErrorState, PageHeader, SectionHeading } from "./ui";
import type { RegisterBeforeNavigate } from "./navigation";

type MemoryLayer = "active" | "important" | `topic:${string}`;
type PreferenceListKey = "keywords" | "exclude_keywords" | "exploration_directions" | "important_anchors";

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

function preferenceLines(preferences: LearningContextPreferences): Record<PreferenceListKey, string> {
  return {
    keywords: toLines(preferences.keywords),
    exclude_keywords: toLines(preferences.exclude_keywords),
    exploration_directions: toLines(preferences.exploration_directions),
    important_anchors: toLines(preferences.important_anchors),
  };
}

function normalizePreferenceDraft(
  preferences: LearningContextPreferences,
  lines: Record<PreferenceListKey, string>,
): LearningContextPreferences {
  return {
    ...preferences,
    keywords: fromLines(lines.keywords),
    exclude_keywords: fromLines(lines.exclude_keywords),
    exploration_directions: fromLines(lines.exploration_directions),
    important_anchors: fromLines(lines.important_anchors),
  };
}

function sourceTypeLabel(type: string) {
  if (type === "paper-note") return "论文笔记";
  if (type === "course-note") return "课程笔记（手动选择）";
  return "学习笔记";
}

function memoryPath(layer: MemoryLayer) {
  return layer.startsWith("topic:") ? `topics/${layer.slice(6)}.md` : `${layer}.md`;
}

function memoryLayerForEntry(entry: LearningContextEditableEntry): MemoryLayer | null {
  if (entry.layer === "active" || entry.layer === "important") return entry.layer;
  return entry.topic_id ? `topic:${entry.topic_id}` : null;
}

function withoutAutomaticEntryBlocks(markdown: string) {
  return markdown
    .replace(
      /^<!-- learning-context-entry \{[^\r\n]*\} -->\r?\n[\s\S]*?^<!-- \/learning-context-entry -->\r?\n?/gm,
      "",
    )
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function LearningContextPage({ registerBeforeNavigate }: { registerBeforeNavigate?: RegisterBeforeNavigate }) {
  const [overview, setOverview] = useState<LearningContextOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [manualReviewEntryIds, setManualReviewEntryIds] = useState<string[]>([]);
  const [pendingEntryFocusId, setPendingEntryFocusId] = useState("");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preferencesDraft, setPreferencesDraft] = useState<LearningContextPreferences | null>(null);
  const [preferenceTextDraft, setPreferenceTextDraft] = useState<Record<PreferenceListKey, string>>({
    keywords: "",
    exclude_keywords: "",
    exploration_directions: "",
    important_anchors: "",
  });
  const [selectedLayer, setSelectedLayer] = useState<MemoryLayer>("active");
  const [memoryText, setMemoryText] = useState("");
  const [memoryOriginal, setMemoryOriginal] = useState("");
  const [memoryLoaded, setMemoryLoaded] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryEditing, setMemoryEditing] = useState(false);
  const [editingEntryId, setEditingEntryId] = useState("");
  const [entryDraftTitle, setEntryDraftTitle] = useState("");
  const [entryDraftSummary, setEntryDraftSummary] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const value = await getLearningContext();
      setOverview(value);
      setSelectedIds(value.sources.included_document_ids);
      setPreferencesDraft(value.preferences);
      setPreferenceTextDraft(preferenceLines(value.preferences));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "无法读取学习进度上下文");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!syncing) return;
    let current = true;
    const refreshProgress = async () => {
      try {
        const value = await getLearningContext();
        if (current) {
          setOverview((previous) => previous
            ? { ...previous, status: value.status }
            : value);
        }
      } catch {
        // The active sync request still reports its final result if polling fails.
      }
    };
    void refreshProgress();
    const timer = window.setInterval(() => void refreshProgress(), 1200);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [syncing]);

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
  const normalizedPreferenceDraft = preferencesDraft
    ? normalizePreferenceDraft(preferencesDraft, preferenceTextDraft)
    : null;
  const preferencesDirty = Boolean(
    overview && normalizedPreferenceDraft
      && JSON.stringify(normalizedPreferenceDraft) !== JSON.stringify(overview.preferences),
  );
  const memoryDirty = memoryEditing && memoryLoaded && memoryText !== memoryOriginal;
  const editableEntries = overview?.editable_entries.filter(
    (entry) => entry.relative_path === memoryPath(selectedLayer),
  ) ?? [];
  const existingReviewEntryIds = overview?.manual_entries
    .filter((entry) => entry.relative_path === memoryPath(selectedLayer) && entry.support_state === "needs_review")
    .map((entry) => entry.entry_id) ?? [];
  const budgetReviewEntryIds = manualReviewEntryIds.filter((entryId) => overview?.editable_entries.some(
    (entry) => entry.entry_id === entryId && entry.relative_path === memoryPath(selectedLayer),
  ));
  const pendingReviewCount = new Set([
    ...existingReviewEntryIds,
    ...budgetReviewEntryIds,
  ]).size;
  const editingEntry = editableEntries.find((entry) => entry.entry_id === editingEntryId);
  const entryDirty = Boolean(editingEntry && (
    entryDraftTitle !== editingEntry.title || entryDraftSummary !== editingEntry.summary
  ));
  const hasUnsavedChanges = sourceDirty || preferencesDirty || memoryDirty || entryDirty;

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
    setEditingEntryId("");
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

  useEffect(() => {
    if (!pendingEntryFocusId || !memoryLoaded || memoryLoading) return;
    const target = document.getElementById(`learning-context-entry-${pendingEntryFocusId}`);
    if (!target) return;
    target.scrollIntoView?.({ behavior: "smooth", block: "center" });
    target.focus();
    setPendingEntryFocusId("");
  }, [editableEntries, memoryLoaded, memoryLoading, pendingEntryFocusId]);

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
    if (!normalizedPreferenceDraft) return;
    setSaving(true);
    setNotice("");
    try {
      await setLearningContextPreferences(normalizedPreferenceDraft);
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
      const result = topicId
        ? await saveLearningContextTopic(topicId, memoryText)
        : await saveLearningContextMemory(selectedLayer as "active" | "important", memoryText);
      setMemoryEditing(false);
      setMemoryOriginal(memoryText);
      await refresh();
      setNotice(result.pinned_entry_ids.length
        ? `已保存；${result.pinned_entry_ids.length} 条修改过的自动条目已单独固定，其他条目仍会继续同步。`
        : "已保存；手动说明会保留，其他自动条目仍会继续同步。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存上下文失败");
    } finally {
      setSaving(false);
    }
  }

  function beginEntryEdit(entry: LearningContextEditableEntry) {
    setEditingEntryId(entry.entry_id);
    setEntryDraftTitle(entry.title);
    setEntryDraftSummary(entry.summary);
  }

  async function saveEntry(entry: LearningContextEditableEntry) {
    if (!entryDraftTitle.trim() || !entryDraftSummary.trim()) {
      setNotice("条目标题和正文都不能为空。");
      return;
    }
    setSaving(true);
    setNotice("");
    try {
      const result = await updateLearningContextEntry(entry.entry_id, {
        layer: entry.layer,
        ...(entry.topic_id ? { topic_id: entry.topic_id } : {}),
        title: entryDraftTitle,
        summary: entryDraftSummary,
      });
      setMemoryText(result.markdown);
      setMemoryOriginal(result.markdown);
      setEditingEntryId("");
      await refresh();
      setNotice("已保存并固定这条知识；其他自动条目仍会继续同步。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存知识条目失败");
    } finally {
      setSaving(false);
    }
  }

  async function changeTopicStatus(status: "current" | "history" | "automatic") {
    if (!topicId) return;
    setSaving(true);
    setNotice("");
    try {
      await setLearningContextTopicStatus(topicId, status);
      await refresh();
      setNotice(status === "current"
        ? "已将专题固定为当前方向。"
        : status === "history"
          ? "已将专题移至历史；内容仍可按需检索。"
          : "已恢复专题的自动整理。"
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "更新专题状态失败");
    } finally {
      setSaving(false);
    }
  }

  async function restoreAutomatic(entryId?: string, confirmSupport = false) {
    setSaving(true);
    setNotice("");
    try {
      await restoreAutomaticLearningContext(
        topicId ? "topic" : selectedLayer as "active" | "important",
        topicId || undefined,
        entryId,
        confirmSupport,
      );
      await refresh();
      setMemoryEditing(false);
      setNotice(confirmSupport
        ? "已确认剩余来源仍支持该条目；它已重新纳入推荐上下文。"
        : entryId
          ? "已解除这条目的固定；下次同步时可自动更新。"
          : "已解除本层条目的固定；现有手动说明会保留，后续同步可更新自动条目。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "恢复自动维护失败");
    } finally {
      setSaving(false);
    }
  }

  async function runSync(force = false, onlySourceId?: string) {
    if (!overview) return;
    if (sourceDirty || preferencesDirty || memoryDirty || entryDirty) {
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
      const ids = result.source_results.flatMap((source) =>
        Array.isArray(source.manual_review_entry_ids)
          ? source.manual_review_entry_ids.filter((entryId): entryId is string => typeof entryId === "string")
          : [],
      );
      setManualReviewEntryIds(Array.from(new Set(ids)));
      setNotice(result.message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "同步学习上下文失败");
    } finally {
      setSyncing(false);
    }
  }

  function changeMemoryLayer(nextLayer: MemoryLayer) {
    if (nextLayer === selectedLayer) return true;
    if ((memoryDirty || entryDirty) && !window.confirm("当前上下文有未保存的修改；放弃修改并切换层级吗？")) {
      return false;
    }
    setSelectedLayer(nextLayer);
    return true;
  }

  if (loading && !overview) return <div className="page-stack"><PageHeader eyebrow="LEARNING PROGRESS" title="学习进度" /><div className="loading-state" role="status">正在读取学习进度…</div></div>;
  if (loadError && !overview) return <div className="page-stack"><PageHeader eyebrow="LEARNING PROGRESS" title="学习进度" /><ErrorState message={loadError} retry={() => void refresh()} /></div>;
  if (!overview || !preferencesDraft) return null;

  const memoryStatusEntries = overview.manual_entries.filter(
    (entry) => entry.relative_path === memoryPath(selectedLayer),
  );
  const restorableEntries = memoryStatusEntries.filter((entry) => entry.pinned || entry.removed);
  const removedSourceEntries = memoryStatusEntries.filter((entry) => entry.support_state === "source_removed");
  const manualMemoryText = withoutAutomaticEntryBlocks(memoryText);
  const syncProgress = overview.status.sync_progress;
  const sourceCount = includedIds.length;
  const topicLayers = overview.topics;
  const selectedTopic = topicLayers.find((topic) => topic.id === topicId);
  const statusCopy = overview.status.message ?? (overview.status.state === "synced" ? "已同步" : "尚未同步");

  return (
    <div className="page-stack learning-context-page">
      <PageHeader
        eyebrow="LEARNING PROGRESS"
        title="学习进度"
        description="手动选择哪些正式笔记参与进度判断；在这里查看、整理和编辑推荐所使用的上下文。"
      />

      {notice && <div className="editor-notice success-notice" role="status">{notice}</div>}
      {manualReviewEntryIds.length > 0 && (
        <section className="learning-sync-review" role="status" aria-label="本次同步待人工核对的条目">
          <div>
            <strong>本次有 {manualReviewEntryIds.length} 条旧知识未进入核对</strong>
            <p>这些条目尚未由本次同步验证。可查看条目原文；当前列表中找不到的条目会显示 ID。</p>
          </div>
          <ul>
            {manualReviewEntryIds.map((entryId) => {
              const entry = overview.editable_entries.find((item) => item.entry_id === entryId);
              const destination = entry ? memoryLayerForEntry(entry) : null;
              const location = entry?.layer === "topic"
                ? topicLayers.find((topic) => topic.id === entry.topic_id)?.title ?? "专题"
                : entry?.layer === "important" ? "重要知识" : "当前关注";
              return (
                <li key={entryId}>
                  {entry && destination ? (
                    <button
                      className="text-button learning-sync-review-link"
                      type="button"
                      onClick={() => {
                        if (changeMemoryLayer(destination)) setPendingEntryFocusId(entryId);
                      }}
                    >
                      查看：{location} · {entry.title}
                    </button>
                  ) : (
                    <strong>{entry?.title ?? entryId}</strong>
                  )}
                  <small>{entry ? `条目 ID：${entryId}` : "当前列表中未找到此条目；请按 ID 查找。"}</small>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {loadError && <ErrorState message={loadError} retry={() => void refresh()} />}

      <section className="learning-context-status surface" aria-live="polite">
        <div><span className={`learning-status-dot learning-status-${overview.status.state}`} /><strong>{statusCopy}</strong></div>
        <span>{sourceCount ? `已纳入 ${sourceCount} 篇正式笔记` : "尚未选择学习资料"}</span>
        {syncing && (
          <div className="learning-sync-progress" role="status">
            {syncProgress?.total_sources
              ? `正在${syncProgress.phase === "analyzing" ? "分析" : "检查"}第 ${syncProgress.source_index}/${syncProgress.total_sources} 篇：${syncProgress.current_source_title || syncProgress.current_source_id || "准备中"}`
              : "正在准备本次同步…"}
            {syncProgress?.total_sources ? (
              <span>已完成 {syncProgress.completed_sources}/{syncProgress.total_sources} 篇。</span>
            ) : null}
            {syncProgress?.phase === "analyzing" && syncProgress.total_batches > 0 ? (
              <span>正在处理第 {syncProgress.batch_index}/{syncProgress.total_batches} 个章节批次（已完成 {syncProgress.completed_batches} 批）。</span>
            ) : null}
            <small>较长笔记可能分多个章节批次；完成后会显示本次分析和跳过数量。</small>
          </div>
        )}
        <div className="learning-panel-actions">
          <button className="button button-primary" type="button" disabled={(!sourceCount && overview.status.state !== "pending") || sourceDirty || saving || syncing || memoryDirty || entryDirty} onClick={() => void runSync()}>
            {syncing ? (syncProgress?.phase === "analyzing" ? "正在分析…" : "正在检查…") : "同步知识变化"}
          </button>
          <button className="button button-secondary" type="button" disabled={!sourceCount || sourceDirty || saving || syncing || memoryDirty || entryDirty} onClick={() => void runSync(true)}>
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
            detail="当前关注、重要知识和历史专题分层保存；修改自动条目只会固定对应条目，其他内容继续同步。"
          />
          <div className="learning-memory-controls">
            <label className="field-label">
              <span>查看层级</span>
              <select value={selectedLayer} onChange={(event) => changeMemoryLayer(event.target.value as MemoryLayer)}>
                <option value="active">当前关注</option>
                <option value="important">重要知识</option>
                {topicLayers.map((topic: LearningContextTopic) => <option value={`topic:${topic.id}`} key={topic.id}>{topic.is_active ? "当前专题" : "历史专题"}：{topic.title}</option>)}
              </select>
            </label>
            <span className={`chip ${restorableEntries.length || pendingReviewCount || removedSourceEntries.length ? "chip-amber" : "chip-green"}`}>
              {pendingReviewCount
                ? `待核对 ${pendingReviewCount} 条`
                : removedSourceEntries.length
                  ? `来源已移除 ${removedSourceEntries.length} 条`
                : restorableEntries.length
                  ? `固定 ${memoryStatusEntries.filter((entry) => entry.pinned).length} 条`
                  : "自动同步"}
            </span>
          </div>
          {selectedTopic && (
            <div className="learning-topic-actions" aria-label="专题方向管理">
              {!selectedTopic.is_active && <button className="button button-secondary" type="button" disabled={saving || syncing || memoryDirty || entryDirty} onClick={() => void changeTopicStatus("current")}>设为当前方向</button>}
              {selectedTopic.is_active && selectedTopic.manual_status !== "history" && <button className="button button-secondary" type="button" disabled={saving || syncing || memoryDirty || entryDirty} onClick={() => void changeTopicStatus("history")}>移至历史</button>}
              {selectedTopic.manual_status === "current" || selectedTopic.manual_status === "history" ? <button className="text-button" type="button" disabled={saving || syncing || memoryDirty || entryDirty} onClick={() => void changeTopicStatus("automatic")}>恢复自动整理</button> : selectedTopic.is_active ? <button className="text-button" type="button" disabled={saving || syncing || memoryDirty || entryDirty} onClick={() => void changeTopicStatus("current")}>固定为当前方向</button> : null}
            </div>
          )}
          <p className="learning-memory-preservation">
            当前关注里的手写说明会补充搜索方向，但不会作为已掌握知识；重要知识与历史专题中的手写说明只作为个人备注。自动同步只更新带有自动条目标记的内容。
          </p>
          {memoryStatusEntries.length > 0 && (
            <div className="learning-memory-entry-list" aria-label="人工条目状态">
              {memoryStatusEntries.map((entry) => (
                <div className="learning-memory-entry-status" key={`${entry.relative_path}:${entry.entry_id}`}>
                  <span>
                    <strong>{entry.title}</strong>
                    <small>{entry.removed
                      ? "已从上下文移除"
                      : entry.support_state === "source_removed"
                        ? "来源已移除，人工内容已保留"
                        : entry.support_state === "needs_review"
                          ? "来源对应关系待核对，暂不用于推荐"
                          : entry.pinned
                            ? "人工固定"
                            : "来源待核对"}</small>
                  </span>
                  {(entry.pinned || entry.removed) && !memoryEditing && !editingEntryId && (
                    <button
                      className="text-button"
                      type="button"
                      disabled={saving}
                      aria-label={entry.removed ? `允许自动补回：${entry.title}` : `解除固定：${entry.title}`}
                      onClick={() => void restoreAutomatic(entry.entry_id)}
                    >
                      {entry.removed ? "允许自动补回" : "解除固定"}
                    </button>
                  )}
                  {entry.support_state === "needs_review" && !memoryEditing && !editingEntryId && (
                    <button
                      className="text-button"
                      type="button"
                      disabled={saving}
                      aria-label={`确认剩余来源支持：${entry.title}`}
                      onClick={() => void restoreAutomatic(entry.entry_id, true)}
                    >
                      确认剩余来源仍支持
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {memoryLoading ? <div className="loading-state" role="status">正在读取上下文…</div> : (
            <>
              <div className="learning-memory-preview">
                {editableEntries.map((entry) => (
                  <article id={`learning-context-entry-${entry.entry_id}`} tabIndex={-1} className="learning-memory-auto-entry" key={entry.entry_id}>
                    {editingEntryId === entry.entry_id ? (
                      <div className="learning-memory-entry-editor">
                        <label className="field-label">
                          <span>知识标题</span>
                          <input value={entryDraftTitle} maxLength={200} onChange={(event) => setEntryDraftTitle(event.target.value)} />
                        </label>
                        <label className="field-label">
                          <span>知识正文</span>
                          <textarea value={entryDraftSummary} maxLength={2000} onChange={(event) => setEntryDraftSummary(event.target.value)} />
                        </label>
                        <div className="learning-panel-actions">
                          <button className="button button-primary" type="button" disabled={saving || !entryDirty} onClick={() => void saveEntry(entry)}>{saving ? "正在保存…" : "保存并固定"}</button>
                          <button className="button button-secondary" type="button" disabled={saving} onClick={() => setEditingEntryId("")}>取消</button>
                          {entryDirty && <span className="learning-unsaved">条目有未保存的修改</span>}
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="learning-memory-auto-entry-heading">
                          <h3>{entry.title}</h3>
                          <button className="text-button" type="button" disabled={saving || syncing || memoryDirty || entryDirty} onClick={() => beginEntryEdit(entry)}>编辑条目</button>
                        </div>
                        <MarkdownContent content={entry.summary} />
                        <small>{entry.pinned ? "人工固定" : "自动维护"}</small>
                      </>
                    )}
                  </article>
                ))}
                {manualMemoryText ? <MarkdownContent content={manualMemoryText} /> : null}
                {!editableEntries.length && !manualMemoryText && (
                  <EmptyState title="这一层还没有内容" description="选择学习资料并同步后会逐步形成上下文；你也可以手动添加自己的说明。" />
                )}
              </div>
              <details className="learning-memory-advanced">
                <summary>高级 Markdown 原文</summary>
                <p>原文包含自动条目的内部标记；日常修改请使用上方的单条编辑。</p>
                {memoryEditing ? (
                  <>
                    <label className="learning-memory-editor">
                      <span className="sr-only">编辑高级 Markdown 原文</span>
                      <textarea value={memoryText} onChange={(event) => setMemoryText(event.target.value)} spellCheck={false} />
                    </label>
                    <div className="learning-panel-actions">
                      <button className="button button-primary" type="button" disabled={saving || !memoryDirty || entryDirty} onClick={() => void saveMemory()}>{saving ? "正在保存…" : "保存上下文"}</button>
                      <button className="button button-secondary" type="button" disabled={saving} onClick={() => { setMemoryText(memoryOriginal); setMemoryEditing(false); }}>取消</button>
                      {memoryDirty && <span className="learning-unsaved">上下文有未保存的修改</span>}
                    </div>
                  </>
                ) : (
                  <div className="learning-panel-actions">
                    <button className="button button-secondary" type="button" disabled={entryDirty || syncing} onClick={() => { setMemoryText(memoryOriginal); setMemoryEditing(true); }}>编辑高级 Markdown 原文</button>
                    {restorableEntries.length > 0 && <button className="text-button" type="button" disabled={saving || syncing || entryDirty} onClick={() => void restoreAutomatic()}>解除本层所有固定</button>}
                  </div>
                )}
              </details>
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
                value={preferenceTextDraft[key]}
                onChange={(event) => setPreferenceTextDraft({ ...preferenceTextDraft, [key]: event.target.value })}
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
