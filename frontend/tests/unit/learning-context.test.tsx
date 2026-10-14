import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { LearningContextPage } from "../../src/LearningContext";
import type { LearningContextOverview } from "../../src/api";

const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");

function overview(): LearningContextOverview {
  return {
    sources: {
      included_document_ids: [],
      missing_document_ids: [],
      available_documents: [
        { id: "gem-note", title: "GEM 学习笔记", type: "learning-note" },
        { id: "network-course", title: "以太网课程笔记", type: "course-note" },
      ],
    },
    preferences: {
      fixed_direction: "",
      keywords: [],
      exclude_keywords: [],
      exploration_directions: [],
      important_anchors: [],
    },
    active: "<!-- learning-context-entry {\"entry_id\":\"current-direction\",\"owner\":\"auto\",\"source_headings\":{\"gem-note\":[\"Mechanism\"]},\"layer\":\"active\",\"title\":\"当前方向\",\"summary\":\"原始自动说明。\"} -->\n### 当前方向\n\n原始自动说明。\n<!-- /learning-context-entry -->\n\n<!-- learning-context-entry {\"entry_id\":\"related-entry\",\"owner\":\"auto\",\"source_headings\":{\"gem-note\":[\"Replay\"]},\"layer\":\"active\",\"title\":\"相关知识\",\"summary\":\"另一条自动说明。\"} -->\n### 相关知识\n\n另一条自动说明。\n<!-- /learning-context-entry -->\n",
    important: "",
    topics: [],
    status: { state: "not_synced", message: "尚未同步" },
    manual_entries: [],
    editable_entries: [
      {
        relative_path: "active.md",
        layer: "active",
        topic_id: null,
        entry_id: "current-direction",
        title: "当前方向",
        summary: "原始自动说明。",
        pinned: false,
        support_state: null,
      },
      {
        relative_path: "active.md",
        layer: "active",
        topic_id: null,
        entry_id: "related-entry",
        title: "相关知识",
        summary: "另一条自动说明。",
        pinned: false,
        support_state: null,
      },
    ],
  };
}

describe("学习进度上下文 page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    if (originalScrollIntoView) {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
    } else {
      delete (HTMLElement.prototype as HTMLElement & { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("lets the user explicitly select notes and saves the scope without an AI request", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "setLearningContextSources").mockImplementation(async (ids) => {
      current = {
        ...current,
        sources: { ...current.sources, included_document_ids: ids },
        status: { state: "pending", message: "新增 1 篇待分析" },
      };
      return current.sources;
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    const gem = await screen.findByRole("checkbox", { name: /GEM 学习笔记/ });
    expect(screen.getByRole("checkbox", { name: /以太网课程笔记/ })).toHaveProperty("checked", false);
    await user.click(gem);
    await user.click(screen.getByRole("button", { name: "保存资料范围" }));

    await waitFor(() => expect(api.setLearningContextSources).toHaveBeenCalledWith(["gem-note"]));
    expect(await screen.findByText("新增 1 篇待分析")).toBeTruthy();
    expect(api.getLearningContext).toHaveBeenCalledTimes(2);
  });

  it("keeps the other section drafts when saving sources and preferences in any order", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "setLearningContextSources").mockImplementation(async (ids) => {
      current = { ...current, sources: { ...current.sources, included_document_ids: ids } };
      return current.sources;
    });
    vi.spyOn(api, "setLearningContextPreferences").mockImplementation(async (preferences) => {
      current = { ...current, preferences };
      return preferences;
    });
    vi.spyOn(api, "saveLearningContextMemory").mockImplementation(async (layer, markdown) => {
      current = { ...current, active: markdown };
      return { layer, markdown, pinned_entry_ids: [] };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    const gem = await screen.findByRole("checkbox", { name: /GEM 学习笔记/ });
    await user.click(gem);
    const keywords = screen.getByLabelText(/搜索关键词/);
    fireEvent.change(keywords, { target: { value: "GEM" } });
    await user.click(screen.getByRole("button", { name: "添加个人说明" }));
    const note = screen.getByLabelText("个人说明 Markdown");
    fireEvent.change(note, { target: { value: "### 自己的方向\n\n人工补充说明。" } });

    await user.click(screen.getByRole("button", { name: "保存搜索偏好" }));
    await waitFor(() => expect(api.setLearningContextPreferences).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("搜索偏好已保存，不会作为已掌握知识。")).toBeTruthy();
    expect(gem).toHaveProperty("checked", true);
    expect(screen.getByLabelText("个人说明 Markdown")).toHaveProperty("value", "### 自己的方向\n\n人工补充说明。");

    fireEvent.change(screen.getByLabelText(/搜索关键词/), { target: { value: "GEM\nEWC" } });
    await user.click(screen.getByRole("button", { name: "保存资料范围" }));
    await waitFor(() => expect(api.setLearningContextSources).toHaveBeenCalledWith(["gem-note"]));
    expect(await screen.findByText("学习资料范围已保存；内容变化会在同步时处理。未发起模型请求。")).toBeTruthy();
    expect(screen.getByLabelText(/搜索关键词/)).toHaveProperty("value", "GEM\nEWC");
    expect(screen.getByLabelText("个人说明 Markdown")).toHaveProperty("value", "### 自己的方向\n\n人工补充说明。");
  });

  it("adds personal Markdown without exposing or changing automatic entry metadata", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    const save = vi.spyOn(api, "saveLearningContextMemory").mockImplementation(async (layer, markdown) => {
      current = { ...current, active: markdown };
      return { layer, markdown, pinned_entry_ids: [] };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "添加个人说明" }));
    fireEvent.change(screen.getByLabelText("个人说明 Markdown"), {
      target: { value: "### 自己的方向\n\n人工补充说明。" },
    });
    expect(screen.getByText("人工补充说明。")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "保存个人说明" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("个人说明已保存；自动知识条目和来源记录保持不变。")).toBeTruthy();
    const saved = save.mock.calls[0][1];
    expect(saved).toContain('"entry_id":"current-direction"');
    expect(saved).toContain('"source_headings":{"gem-note":["Mechanism"]}');
    expect(saved).toContain("人工补充说明。");
    expect(saved).toContain('"entry_id":"related-entry"');
    expect(current.active).toContain("### 自己的方向");
    expect(await screen.findByText("人工补充说明。")).toBeTruthy();
    expect(screen.getAllByText("自动维护")).toHaveLength(2);
  });

  it("restores the latest over-budget review links from the saved sync result", async () => {
    const current = overview();
    current.topics = [{ id: "continual-learning", title: "持续学习", aliases: [], keywords: [] }];
    current.editable_entries.push({
      relative_path: "topics/continual-learning.md",
      layer: "topic",
      topic_id: "continual-learning",
      entry_id: "old-entry",
      title: "待核对的旧知识",
      summary: "仍保留的正文。",
      pinned: false,
      support_state: null,
    });
    current.status = {
      state: "synced",
      message: "最近一次同步有旧知识待核对",
      last_result: [{ source_id: "gem-note", manual_review_entry_ids: ["old-entry"] }],
    };
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "getLearningContextTopic").mockResolvedValue({
      ...current.topics[0],
      markdown: '<!-- learning-context-entry {"entry_id":"old-entry","owner":"auto","source_headings":{"gem-note":["Mechanism"]},"layer":"topic","title":"待核对的旧知识","summary":"仍保留的正文。"} -->\n### 待核对的旧知识\n\n仍保留的正文。\n<!-- /learning-context-entry -->\n',
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    expect(await screen.findByText("本次有 1 条旧知识未进入核对")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "查看：持续学习 · 待核对的旧知识" }));
    expect((await screen.findAllByText("仍保留的正文。")).length).toBeGreaterThan(0);
  });

  it("shows source note titles separately from automatic knowledge summaries", async () => {
    const current = overview();
    current.sources.available_documents[0].title = "GEM 论文学习笔记";
    current.editable_entries[0].summary = "gem-note：原始自动说明。";
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    const user = userEvent.setup();
    render(<LearningContextPage />);

    expect(await screen.findByText("原始自动说明。")).toBeTruthy();
    expect(screen.queryByText("gem-note：原始自动说明。")).toBeNull();
    const sources = screen.getByText("来源笔记").closest("details");
    expect(sources).toBeTruthy();
    await user.click(screen.getByText("来源笔记"));
    expect(within(sources as HTMLElement).getByText("GEM 论文学习笔记")).toBeTruthy();
  });

  it("preserves a manual context edit and exposes an explicit restore action", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "saveLearningContextMemory").mockImplementation(async (layer, markdown) => {
      current = {
        ...current,
        active: markdown,
        manual_entries: [{
          relative_path: "active.md",
          entry_id: "current-direction",
          title: "当前方向",
          pinned: true,
          removed: false,
          support_state: null,
        }],
      };
      return { layer, markdown, pinned_entry_ids: ["current-direction"] };
    });
    vi.spyOn(api, "restoreAutomaticLearningContext").mockImplementation(async (_layer, _topicId, entryId) => {
      current = {
        ...current,
        manual_entries: current.manual_entries.filter((item) => item.entry_id !== entryId),
      };
      return { relative_path: "active.md", markdown: current.active, manual_entries: current.manual_entries };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await screen.findByText("当前方向");
    await user.click(screen.getByText("高级 Markdown 原文"));
    await user.click(screen.getByRole("button", { name: "编辑高级 Markdown 原文" }));
    const editor = screen.getByLabelText("编辑高级 Markdown 原文");
    const edited = current.active.replace("原始自动说明。", "人工方向说明。");
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByRole("button", { name: "保存上下文" }));

    await waitFor(() => expect(api.saveLearningContextMemory).toHaveBeenCalledWith(
      "active",
      edited,
    ));
    expect(await screen.findByText("固定 1 条")).toBeTruthy();
    expect(await screen.findByText("人工固定")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "解除固定：当前方向" }));
    await waitFor(() => expect(api.restoreAutomaticLearningContext).toHaveBeenCalledWith(
      "active", undefined, "current-direction", false,
    ));
    expect(await screen.findByText("自动同步")).toBeTruthy();
    expect(current.active).toContain("人工方向说明。");
  });

  it("saves search preferences as search intent rather than mastery evidence", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "setLearningContextPreferences").mockImplementation(async (preferences) => {
      current = { ...current, preferences };
      return preferences;
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    const direction = await screen.findByLabelText("固定研究方向");
    fireEvent.change(direction, { target: { value: "Continual Learning" } });
    const keywords = screen.getByLabelText(/搜索关键词/);
    await user.type(keywords, "GEM{enter}EWC");
    await user.click(screen.getByRole("button", { name: "保存搜索偏好" }));

    await waitFor(() => expect(api.setLearningContextPreferences).toHaveBeenCalledWith({
      fixed_direction: "Continual Learning",
      keywords: ["GEM", "EWC"],
      exclude_keywords: [],
      exploration_directions: [],
      important_anchors: [],
    }));
    expect(screen.getByText("搜索偏好已保存，不会作为已掌握知识。")).toBeTruthy();
    expect(current.sources.included_document_ids).toEqual([]);
  });

  it("asks before discarding unsaved Markdown when switching memory layers", async () => {
    const current = overview();
    current.topics = [{
      id: "continual-learning",
      title: "持续学习",
      aliases: [],
      keywords: [],
    }];
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "getLearningContextTopic").mockResolvedValue({
      ...current.topics[0],
      markdown: "### 专题内容",
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByText("高级 Markdown 原文"));
    await user.click(await screen.findByRole("button", { name: "编辑高级 Markdown 原文" }));
    expect(screen.getByText(/手写说明会补充搜索方向，但不会作为已掌握知识/)).toBeTruthy();
    const editor = screen.getByLabelText("编辑高级 Markdown 原文");
    fireEvent.change(editor, { target: { value: "尚未保存的说明" } });
    const layerPicker = screen.getByLabelText("查看层级");
    await user.selectOptions(layerPicker, "topic:continual-learning");

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("未保存的修改"));
    expect(layerPicker).toHaveProperty("value", "active");
    expect(screen.getByLabelText("编辑高级 Markdown 原文")).toHaveProperty(
      "value",
      "尚未保存的说明",
    );
    expect(api.getLearningContextTopic).not.toHaveBeenCalled();
  });

  it("lets the user set an indexed topic as the current direction", async () => {
    let current = overview();
    current.topics = [{
      id: "continual-learning",
      title: "持续学习",
      aliases: [],
      keywords: [],
      is_active: false,
      manual_status: null,
    }];
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "getLearningContextTopic").mockResolvedValue({
      ...current.topics[0],
      markdown: "### GEM",
    });
    vi.spyOn(api, "setLearningContextTopicStatus").mockImplementation(async (topicId, status) => {
      current = {
        ...current,
        topics: current.topics.map((topic) => topic.id === topicId
          ? { ...topic, is_active: status === "current", manual_status: status === "automatic" ? null : status }
          : topic),
      };
      return { ...current.topics[0], markdown: "### GEM" };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.selectOptions(await screen.findByLabelText("查看层级"), "topic:continual-learning");
    await user.click(await screen.findByRole("button", { name: "设为当前方向" }));

    await waitFor(() => expect(api.setLearningContextTopicStatus).toHaveBeenCalledWith(
      "continual-learning",
      "current",
    ));
    expect(await screen.findByText("已将专题固定为当前方向。")).toBeTruthy();
  });

  it("edits one automatic entry without exposing metadata or pinning other entries", async () => {
    let current = overview();
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => structuredClone(current));
    vi.spyOn(api, "updateLearningContextEntry").mockImplementation(async (entryId, value) => {
      const savedMarkdown = current.active
        .replace('"title":"当前方向"', `"title":"${value.title}"`)
        .replace('"summary":"原始自动说明。"', `"summary":"${value.summary}"`)
        .replace("原始自动说明。", value.summary);
      current = {
        ...current,
        active: savedMarkdown,
        editable_entries: current.editable_entries.map((entry) => entry.entry_id === entryId
          ? { ...entry, title: value.title, summary: value.summary, pinned: true }
          : entry),
        manual_entries: [{
          relative_path: "active.md",
          entry_id: entryId,
          title: value.title,
          pinned: true,
          removed: false,
          support_state: null,
        }],
      };
      return {
        relative_path: "active.md",
        entry_id: entryId,
        title: value.title,
        summary: value.summary,
        pinned: true,
        markdown: savedMarkdown,
        manual_entries: current.manual_entries,
      };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    expect(await screen.findByText("当前方向")).toBeTruthy();
    expect(screen.getByText("相关知识")).toBeTruthy();
    expect(screen.queryByText(/learning-context-entry/)).toBeNull();
    await user.click(screen.getAllByRole("button", { name: "编辑条目" })[0]);
    fireEvent.change(screen.getByLabelText("知识标题"), { target: { value: "修订后的方向" } });
    fireEvent.change(screen.getByLabelText("知识正文"), { target: { value: "修订后的说明。" } });
    await user.click(screen.getByRole("button", { name: "保存并固定" }));

    await waitFor(() => expect(api.updateLearningContextEntry).toHaveBeenCalledWith(
      "current-direction",
      { layer: "active", title: "修订后的方向", summary: "修订后的说明。" },
    ));
    expect(await screen.findByRole("heading", { name: "修订后的方向" })).toBeTruthy();
    expect(screen.getByText("修订后的说明。")).toBeTruthy();
    expect(screen.getByText("相关知识")).toBeTruthy();
    expect(screen.getByText("自动维护")).toBeTruthy();
    expect(screen.getAllByText("人工固定")).toHaveLength(2);
  });

  it("runs learning context sync only after the user presses its explicit action", async () => {
    const current = overview();
    current.sources.included_document_ids = ["gem-note"];
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "syncLearningContext").mockResolvedValue({
      state: "synced",
      message: "同步完成：分析 1 篇，跳过 0 篇。",
      analyzed_count: 1,
      skipped_count: 0,
      source_results: [],
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "同步知识变化" }));

    await waitFor(() => expect(api.syncLearningContext).toHaveBeenCalledWith({ force: false }));
    expect(await screen.findByText("同步完成：分析 1 篇，跳过 0 篇。")).toBeTruthy();
  });

  it("lists over-budget entries by topic and jumps to the preserved original text", async () => {
    const current = overview();
    current.sources.included_document_ids = ["gem-note"];
    current.topics = [{ id: "continual-learning", title: "持续学习", aliases: [], keywords: [] }];
    current.editable_entries = Array.from({ length: 16 }, (_, index) => ({
      relative_path: "topics/continual-learning.md",
      layer: "topic" as const,
      topic_id: "continual-learning",
      entry_id: `chapter-${String(index + 1).padStart(2, "0")}-entry`,
      title: `旧知识 ${index + 1}`,
      summary: `原始正文 ${index + 1} 完整保留。`,
      pinned: false,
      support_state: null,
    }));
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "getLearningContextTopic").mockResolvedValue({
      id: "continual-learning",
      title: "持续学习",
      aliases: [],
      keywords: [],
      markdown: "专题正文由独立存储返回。",
    });
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const sync = vi.spyOn(api, "syncLearningContext").mockResolvedValue({
      state: "synced",
      message: "同步完成：4 条旧知识超出单次核对预算。",
      analyzed_count: 1,
      skipped_count: 0,
      source_results: [{
        source_id: "gem-note",
        manual_review_entry_ids: [
          "chapter-13-entry",
          "chapter-14-entry",
          "chapter-15-entry",
          "chapter-16-entry",
        ],
      }],
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "同步知识变化" }));

    expect(await screen.findByText("本次有 4 条旧知识未进入核对")).toBeTruthy();
    expect(screen.getByRole("button", { name: "查看：持续学习 · 旧知识 13" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "查看：持续学习 · 旧知识 16" })).toBeTruthy();
    expect(screen.getByText("条目 ID：chapter-13-entry")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "查看：持续学习 · 旧知识 13" }));
    expect(await screen.findByText("原始正文 13 完整保留。")).toBeTruthy();
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" }));
    expect(screen.getByText("待核对 4 条")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "同步知识变化" }));
    await waitFor(() => expect(sync).toHaveBeenCalledTimes(2));
    expect(screen.getByText("本次有 4 条旧知识未进入核对")).toBeTruthy();
    expect(screen.getByText("原始正文 13 完整保留。")).toBeTruthy();
    expect(screen.getByText("待核对 4 条")).toBeTruthy();
  });

  it("shows the ID when an over-budget entry is absent from the current list", async () => {
    const current = overview();
    current.sources.included_document_ids = ["gem-note"];
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "syncLearningContext").mockResolvedValue({
      state: "synced",
      message: "同步完成：1 条旧知识超出单次核对预算。",
      analyzed_count: 1,
      skipped_count: 0,
      source_results: [{ source_id: "gem-note", manual_review_entry_ids: ["missing-entry"] }],
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "同步知识变化" }));

    expect(await screen.findByText("missing-entry")).toBeTruthy();
    expect(screen.getByText("当前列表中未找到此条目；请按 ID 查找。")).toBeTruthy();
  });

  it("shows chapter batch progress while a long sync is still running", async () => {
    const current = overview();
    current.sources.included_document_ids = ["gem-note"];
    let resolveSync: ((value: api.LearningContextSyncResult) => void) | undefined;
    vi.spyOn(api, "getLearningContext").mockImplementation(async () => ({
      ...structuredClone(current),
      status: {
        state: "syncing",
        message: "正在分析所选学习资料",
        sync_progress: {
          phase: "analyzing",
          completed_sources: 0,
          total_sources: 1,
          source_index: 1,
          completed_batches: 1,
          total_batches: 3,
          batch_index: 2,
          current_source_id: "gem-note",
          current_source_title: "GEM 学习笔记",
        },
      },
    }));
    vi.spyOn(api, "syncLearningContext").mockImplementation(() => new Promise((resolve) => {
      resolveSync = resolve;
    }));
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "同步知识变化" }));
    expect(await screen.findByText("正在分析第 1/1 篇：GEM 学习笔记", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText("正在处理第 2/3 个章节批次（已完成 1 批）。")).toBeTruthy();

    resolveSync?.({
      state: "synced",
      message: "同步完成：分析 1 篇，跳过 0 篇。",
      analyzed_count: 1,
      skipped_count: 0,
      source_results: [],
    });
    expect(await screen.findByText("同步完成：分析 1 篇，跳过 0 篇。")).toBeTruthy();
  });

  it("confirms and reanalyzes only the selected note when requested", async () => {
    const current = overview();
    current.sources.included_document_ids = ["gem-note"];
    vi.spyOn(api, "getLearningContext").mockResolvedValue(current);
    vi.spyOn(api, "syncLearningContext").mockResolvedValue({
      state: "synced",
      message: "同步完成：分析 1 篇，跳过 0 篇。",
      analyzed_count: 1,
      skipped_count: 0,
      source_results: [],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await user.click(await screen.findByRole("button", { name: "重新分析这篇" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("GEM 学习笔记"));
    await waitFor(() => expect(api.syncLearningContext).toHaveBeenCalledWith({
      force: true,
      source_id: "gem-note",
    }));
  });
});
