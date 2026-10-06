import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EntitySummary, TermMergePreview } from "../../src/api";
import { TermsPage } from "../../src/pages/BrowsePages";

const api = vi.hoisted(() => ({
  listAllEntities: vi.fn(),
  previewTermMerge: vi.fn(),
  mergeTerms: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

const terms: EntitySummary[] = [
  {
    id: "survivor-term",
    title: "Survivor Term",
    entity_type: "term",
    metadata: { type: "concept", depth: "standard", aliases: ["Current Alias"] },
  },
  {
    id: "loser-term",
    title: "Loser Term",
    entity_type: "term",
    metadata: { type: "entity", depth: "stub", aliases: ["Former Alias"] },
  },
  {
    id: "word-term",
    title: "Word Term",
    entity_type: "term",
    metadata: { type: "vocabulary", depth: "deep", aliases: [] },
  },
];

describe("Terms Registry controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAllEntities.mockResolvedValue(terms);
  });

  it("filters Registry entries by all three Term types", async () => {
    render(<TermsPage onOpen={vi.fn()} />);

    expect(await screen.findByText("Survivor Term")).not.toBeNull();
    expect(screen.getByText("Loser Term")).not.toBeNull();
    expect(screen.getByText("Word Term")).not.toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("类别"), "entity");

    expect(screen.getByText("Loser Term")).not.toBeNull();
    expect(screen.queryByText("Survivor Term")).toBeNull();
    expect(screen.queryByText("Word Term")).toBeNull();
  });

  it("previews aliases and requires confirmation when loser bodies will be discarded", async () => {
    const preview: TermMergePreview = {
      survivor_term_id: "survivor-term",
      loser_term_ids: ["loser-term"],
      final_title: "Survivor Term",
      aliases: ["Current Alias", "Loser Term", "Former Alias", "loser-term"],
      loser_bodies_not_merged: ["loser-term"],
    };
    api.previewTermMerge.mockImplementation(async (input) => ({
      ...preview,
      final_title: input.final_title,
    }));
    api.mergeTerms.mockResolvedValue({
      ...preview,
      commit_revision: "a".repeat(40),
      warnings: [],
    });
    api.listAllEntities
      .mockResolvedValueOnce(terms)
      .mockResolvedValueOnce([terms[0]]);
    const user = userEvent.setup();
    render(<TermsPage onOpen={vi.fn()} />);

    await screen.findByText("Loser Term");
    await user.click(screen.getByRole("checkbox", { name: "选择 Survivor Term" }));
    await user.click(screen.getByRole("checkbox", { name: "选择 Loser Term" }));
    await user.click(screen.getByRole("button", { name: /合并所选/ }));

    expect(await screen.findByText("最终别名")).not.toBeNull();
    expect((await screen.findAllByText("Former Alias")).length).toBeGreaterThan(0);
    expect(screen.getByText("以下条目的正文会随合并删除，不会复制到 Survivor：")).not.toBeNull();
    const confirmButton = screen.getByRole("button", { name: "确认合并" });
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

    await user.click(screen.getByRole("checkbox", { name: "我确认继续，且不合并这些正文" }));
    expect((confirmButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(confirmButton);

    await waitFor(() => expect(api.mergeTerms).toHaveBeenCalledWith({
      survivor_term_id: "survivor-term",
      loser_term_ids: ["loser-term"],
      final_title: "Survivor Term",
      confirm_loser_bodies_not_merged: true,
    }));
    expect((await screen.findByRole("status")).textContent).toContain("已将 1 个 Term 合并到 Survivor Term。");
    await waitFor(() => expect(screen.queryByText("Loser Term")).toBeNull());
  });
});
