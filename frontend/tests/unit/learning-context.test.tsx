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
    active: "# 当前方向\n\n持续学习。\n",
    important: "",
    topics: [],
    status: { state: "not_synced", message: "尚未同步" },
    user_managed_files: [],
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
        user_managed_files: ["active.md"],
      };
      return { layer, markdown, user_managed: true };
    });
    vi.spyOn(api, "restoreAutomaticLearningContext").mockImplementation(async () => {
      current = { ...current, user_managed_files: [] };
      return { relative_path: "active.md", markdown: current.active, user_managed: false };
    });
    const user = userEvent.setup();
    render(<LearningContextPage />);

    await screen.findByText("当前方向");
    await user.click(screen.getByRole("button", { name: "编辑这一层" }));
    const editor = screen.getByLabelText("编辑学习上下文 Markdown");
    fireEvent.change(editor, { target: { value: "# 人工方向\n\n保留我的说明。\n" } });
    await user.click(screen.getByRole("button", { name: "保存并固定" }));

    await waitFor(() => expect(api.saveLearningContextMemory).toHaveBeenCalledWith(
      "active",
      "# 人工方向\n\n保留我的说明。\n",
    ));
    expect(await screen.findByText("人工维护")).toBeTruthy();
    expect(await screen.findByText("人工方向")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "恢复自动维护" }));
    await waitFor(() => expect(api.restoreAutomaticLearningContext).toHaveBeenCalledWith("active", undefined));
    expect(await screen.findByText("自动维护")).toBeTruthy();
    expect(current.active).toBe("# 人工方向\n\n保留我的说明。\n");
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
    fireEvent.change(screen.getByLabelText(/搜索关键词/), { target: { value: "GEM\nEWC" } });
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
});
