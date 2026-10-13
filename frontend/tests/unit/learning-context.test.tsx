import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { LearningContextPage } from "../../src/LearningContext";
import type { LearningContextOverview } from "../../src/api";

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
    active: "<!-- learning-context-entry {\"entry_id\":\"current-direction\",\"owner\":\"auto\",\"source_headings\":{\"gem-note\":[\"Mechanism\"]},\"layer\":\"active\",\"title\":\"当前方向\",\"summary\":\"原始自动说明。\"} -->\n### 当前方向\n\n原始自动说明。\n<!-- /learning-context-entry -->\n",
    important: "",
    topics: [],
    status: { state: "not_synced", message: "尚未同步" },
    manual_entries: [],
  };
}

describe("学习进度上下文 page", () => {
  afterEach(() => vi.restoreAllMocks());

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
    await user.click(screen.getByRole("button", { name: "编辑这一层" }));
    const editor = screen.getByLabelText("编辑学习上下文 Markdown");
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
    expect(screen.getByText(/不会作为已掌握知识/)).toBeTruthy();
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

    await user.click(await screen.findByRole("button", { name: "编辑这一层" }));
    const editor = screen.getByLabelText("编辑学习上下文 Markdown");
    fireEvent.change(editor, { target: { value: "尚未保存的说明" } });
    const layerPicker = screen.getByLabelText("查看层级");
    await user.selectOptions(layerPicker, "topic:continual-learning");

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("未保存的修改"));
    expect(layerPicker).toHaveProperty("value", "active");
    expect(screen.getByLabelText("编辑学习上下文 Markdown")).toHaveProperty(
      "value",
      "尚未保存的说明",
    );
    expect(api.getLearningContextTopic).not.toHaveBeenCalled();
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
