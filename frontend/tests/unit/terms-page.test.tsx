import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Draft, EntitySummary, TermCandidate, TermMergePreview } from "../../src/api";
import { TermsPage } from "../../src/pages/BrowsePages";

const api = vi.hoisted(() => ({
  listAllEntities: vi.fn(),
  listTermCandidates: vi.fn(),
  previewTermMerge: vi.fn(),
  mergeTerms: vi.fn(),
  acceptTermCandidate: vi.fn(),
  createCandidateTermDraft: vi.fn(),
  rejectTermCandidate: vi.fn(),
  requestCandidateTermDraftProposal: vi.fn(),
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

const candidate = (overrides: Partial<TermCandidate>): TermCandidate => ({
  id: "candidate-new",
  normalized_name: "adaptive token pruning",
  display_name: "Adaptive Token Pruning",
  suggested_type: "concept",
  suggested_term_id: null,
  status: "pending",
  draft_id: null,
  accepted_term_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  reviewed_at: null,
  evidence: [{
    id: "evidence-one",
    candidate_id: "candidate-new",
    origin_type: "document",
    origin_id: "note-one",
    origin_title: "Note One",
    origin_rejected: false,
    mention: "adaptive token pruning",
    context_excerpt: "Adaptive token pruning reduces redundant tokens.",
    confidence: 0.9,
    rationale: "A reusable technique.",
    discovered_at: "2026-01-01T00:00:00Z",
  }],
  ...overrides,
});

const candidates = [
  candidate({}),
  candidate({
    id: "candidate-existing",
    normalized_name: "calibrated optimizer",
    display_name: "Calibrated Optimizer",
    suggested_type: "entity",
    suggested_term_id: "survivor-term",
    evidence: [{
      id: "evidence-two",
      candidate_id: "candidate-existing",
      origin_type: "document",
      origin_id: "note-two",
      origin_title: "Note Two",
      origin_rejected: false,
      mention: "Calibrated Optimizer",
      context_excerpt: "The Calibrated Optimizer improves convergence.",
      confidence: 0.84,
      rationale: "Matches an existing entity.",
      discovered_at: "2026-01-02T00:00:00Z",
    }],
  }),
  candidate({
    id: "candidate-research",
    normalized_name: "research reading phrase",
    display_name: "Research Reading Phrase",
    suggested_type: "vocabulary",
    status: "drafting",
    draft_id: "draft-research",
    evidence: [{
      id: "evidence-research",
      candidate_id: "candidate-research",
      origin_type: "external",
      origin_id: "ref:paper-1",
      origin_title: "Paper record",
      origin_rejected: false,
      mention: "research reading phrase",
      context_excerpt: null,
      confidence: 0.72,
      rationale: "Useful in research reading.",
      discovered_at: "2026-01-03T00:00:00Z",
    }],
  }),
  candidate({ id: "candidate-closed", status: "accepted", display_name: "Closed Candidate" }),
];

describe("Terms Registry controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAllEntities.mockResolvedValue(terms);
    api.listTermCandidates.mockResolvedValue(candidates);
    api.acceptTermCandidate.mockResolvedValue({});
    api.rejectTermCandidate.mockResolvedValue({});
    api.requestCandidateTermDraftProposal.mockResolvedValue({});
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
      selected_terms: [
        { id: "survivor-term", title: "Survivor Term", type: "concept", depth: "standard" },
        { id: "loser-term", title: "Loser Term", type: "entity", depth: "stub" },
      ],
      type_conflict: true,
      depth_conflict: true,
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
    expect(screen.getByText("所选 Terms 的类型与深度")).not.toBeNull();
    expect(screen.getByText("以下条目的正文会随合并删除，不会复制到 Survivor：")).not.toBeNull();
    const confirmButton = screen.getByRole("button", { name: "确认合并" });
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

    await user.selectOptions(screen.getByLabelText("最终类型"), "entity");
    await user.selectOptions(screen.getByLabelText("最终深度"), "stub");
    await user.click(screen.getByRole("checkbox", { name: "我确认继续，且不合并这些正文" }));
    expect((confirmButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(confirmButton);

    await waitFor(() => expect(api.mergeTerms).toHaveBeenCalledWith({
      survivor_term_id: "survivor-term",
      loser_term_ids: ["loser-term"],
      final_title: "Survivor Term",
      confirm_loser_bodies_not_merged: true,
      final_type: "entity",
      final_depth: "stub",
    }));
    expect((await screen.findByRole("status")).textContent).toContain("已将 1 个 Term 合并到 Survivor Term。");
    await waitFor(() => expect(screen.queryByText("Loser Term")).toBeNull());
  });

  it("filters Candidate review and links a selected Registry Term", async () => {
    api.acceptTermCandidate.mockResolvedValue({});
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);

    expect(await screen.findByText("Adaptive Token Pruning")).not.toBeNull();
    expect(screen.getByText("Calibrated Optimizer")).not.toBeNull();
    expect(screen.getByText("Research Reading Phrase")).not.toBeNull();
    expect(screen.queryByText("Closed Candidate")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Notes" }));
    expect(screen.queryByText("Research Reading Phrase")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.selectOptions(screen.getByLabelText("类别"), "entity");
    expect(screen.queryByText("Adaptive Token Pruning")).toBeNull();
    expect(screen.getByText("Calibrated Optimizer")).not.toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("类别"), "");

    await userEvent.click(screen.getByRole("button", { name: "Choose Another Existing…" }));
    await userEvent.type(screen.getByLabelText("搜索 Term"), "Loser Term");
    await userEvent.click(screen.getByRole("option", { name: /Loser Term/ }));
    await userEvent.click(screen.getByRole("button", { name: "链接到所选 Term" }));

    await waitFor(() => expect(api.acceptTermCandidate).toHaveBeenCalledWith("candidate-existing", "loser-term"));
  });

  it("requires explicit consent before creating a Candidate Term Draft and AI Proposal", async () => {
    const draft: Draft = {
      id: "draft-adaptive",
      entity_type: "term",
      entity_id: "adaptive-token-pruning",
      base_git_revision: "a".repeat(40),
      base_content_hash: "b".repeat(64),
      content: "---\nid: adaptive-token-pruning\n---\n",
      revision: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    api.createCandidateTermDraft.mockResolvedValue({
      candidate: candidate({ status: "drafting", draft_id: draft.id }),
      draft,
      created: true,
    });
    const onOpen = vi.fn();
    render(<TermsPage onOpen={onOpen} initialTab="candidates" />);

    await userEvent.click(await screen.findByRole("button", { name: "Create Term" }));
    const generate = screen.getByRole("button", { name: "同意并生成建议" });
    expect((generate as HTMLButtonElement).disabled).toBe(true);
    expect(api.createCandidateTermDraft).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("checkbox", { name: /我同意将上述信息发送给 DeepSeek/ }));
    await userEvent.click(generate);

    await waitFor(() => expect(api.createCandidateTermDraft).toHaveBeenCalledWith("candidate-new"));
    await waitFor(() => expect(api.requestCandidateTermDraftProposal).toHaveBeenCalledWith(draft.id, "candidate-new"));
    expect(api.createCandidateTermDraft.mock.invocationCallOrder[0]).toBeLessThan(api.requestCandidateTermDraftProposal.mock.invocationCallOrder[0]);
    expect(onOpen).toHaveBeenCalledWith("term", "adaptive-token-pruning");
  });

  it("allows Create Term from an active external Candidate source", async () => {
    api.listTermCandidates.mockResolvedValue([
      candidate({
        id: "candidate-external",
        normalized_name: "external evidence term",
        display_name: "External Evidence Term",
        evidence: [{
          id: "evidence-external",
          candidate_id: "candidate-external",
          origin_type: "external",
          origin_id: "ref:42",
          origin_title: "Paper record",
          origin_rejected: false,
          mention: "external evidence term",
          context_excerpt: "A bounded external excerpt.",
          confidence: 0.8,
          rationale: "Useful context from the external source.",
          discovered_at: "2026-01-04T00:00:00Z",
        }],
      }),
    ]);
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);

    const createButton = await screen.findByRole("button", { name: "Create Term" });
    expect((createButton as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(createButton);
    expect(screen.getByText(/候选来源的摘录和分析理由/)).not.toBeNull();
    expect(screen.getByText("External · Paper record")).not.toBeNull();
    expect(screen.getAllByText("A bounded external excerpt.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Useful context from the external source.").length).toBeGreaterThan(0);
  });
});
