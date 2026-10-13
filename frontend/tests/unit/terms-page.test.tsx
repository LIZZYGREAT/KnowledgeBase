import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Draft, EntityDetail, EntitySummary, TermCandidate, TermMergePreview } from "../../src/api";
import { TermsPage } from "../../src/pages/BrowsePages";
import { entityWorkspaceUrl } from "../../src/workspaceRoute";

const api = vi.hoisted(() => ({
  listAllEntities: vi.fn(),
  getEntity: vi.fn(),
  getDraft: vi.fn(),
  listDrafts: vi.fn(),
  listProposals: vi.fn(),
  listTaxonomy: vi.fn(),
  listTermCandidates: vi.fn(),
  getTermDiscoveryState: vi.fn(),
  listTermDiscoveryRuns: vi.fn(),
  previewTermMerge: vi.fn(),
  mergeTerms: vi.fn(),
  acceptTermCandidate: vi.fn(),
  createCandidateTermDraft: vi.fn(),
  deleteTermCandidate: vi.fn(),
  rejectTermCandidate: vi.fn(),
  requestCandidateTermDraftProposal: vi.fn(),
}));

const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
const scrollIntoViewSpy = vi.fn();

afterEach(() => {
  if (originalScrollIntoView) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: originalScrollIntoView });
  else delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
});

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

vi.mock("../../src/reader/readerModel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/reader/readerModel")>()),
  hashText: vi.fn().mockResolvedValue("hash"),
}));

const terms: EntitySummary[] = [
  {
    id: "survivor-term",
    title: "Survivor Term",
    entity_type: "term",
    metadata: { type: "concept", depth: "standard", aliases: ["Current Alias"], domains: ["ai"], topics: ["agents"] },
  },
  {
    id: "loser-term",
    title: "Loser Term",
    entity_type: "term",
    metadata: { type: "entity", depth: "stub", aliases: ["Former Alias"], domains: ["biology"], topics: ["methods"] },
  },
  {
    id: "word-term",
    title: "Word 术语",
    entity_type: "term",
    metadata: { type: "vocabulary", depth: "deep", aliases: [], domains: [], topics: [] },
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
    origin_title: "笔记 One",
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
      origin_title: "笔记 Two",
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
    display_name: "论文推荐 Reading Phrase",
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
  candidate({ id: "candidate-closed", status: "accepted", display_name: "Closed 候选" }),
];

describe("术语 术语库 controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listAllEntities.mockResolvedValue(terms);
    api.getEntity.mockResolvedValue(null);
    api.listTaxonomy.mockImplementation(async (kind: string) => kind === "domain"
      ? [{ id: "ai", title: "Artificial Intelligence", kind: "domain" }, { id: "biology", title: "Biology", kind: "domain" }]
      : [{ id: "agents", title: "Agents", kind: "topic" }, { id: "methods", title: "Methods", kind: "topic" }]);
    api.listTermCandidates.mockResolvedValue(candidates);
    api.deleteTermCandidate.mockResolvedValue({ deleted: true });
    api.getTermDiscoveryState.mockResolvedValue({
      settings: {
        enabled_lanes: ["concept", "entity", "vocabulary"],
        daily_max_new: 5,
        lane_capacities: { concept: 5, entity: 4, vocabulary: 6 },
        source_preferences: [],
        focus_override: null,
        external_enabled: false,
      },
      open_count: 0,
      global_capacity: 12,
      daily_remaining: 5,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 5, entity: 4, vocabulary: 6 },
      last_run: null,
    });
    api.listTermDiscoveryRuns.mockResolvedValue([]);
    api.listDrafts.mockResolvedValue([]);
    api.listProposals.mockResolvedValue([]);
    api.acceptTermCandidate.mockResolvedValue({});
    api.rejectTermCandidate.mockResolvedValue({});
    api.requestCandidateTermDraftProposal.mockResolvedValue({});
  });

  it("filters 术语库 entries by all three 术语 types", async () => {
    render(<TermsPage onOpen={vi.fn()} />);

    expect(await screen.findByText("Survivor Term")).not.toBeNull();
    expect(screen.getByText("Loser Term")).not.toBeNull();
    expect(screen.getByText("Word 术语")).not.toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("类别"), "entity");

    expect(screen.getByText("Loser Term")).not.toBeNull();
    expect(screen.queryByText("Survivor Term")).toBeNull();
    expect(screen.queryByText("Word 术语")).toBeNull();
  });

  it("sends 术语 tab selections to their matching URLs", async () => {
    const navigate = vi.fn();
    render(<TermsPage onOpen={vi.fn()} navigate={navigate} />);
    await screen.findByText("Survivor Term");

    await userEvent.click(screen.getByRole("tab", { name: "待处理" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms?tab=candidates");
    await userEvent.click(screen.getByRole("tab", { name: "笔记提及" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms?tab=mentions");
    await userEvent.click(screen.getByRole("tab", { name: "发现术语" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms?tab=discovery");
    await userEvent.click(screen.getByRole("tab", { name: "术语库" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms");
  });

  it("searches 术语库 titles, IDs and aliases and filters by 领域 and 主题", async () => {
    render(<TermsPage onOpen={vi.fn()} />);

    expect(await screen.findByText("Survivor Term")).not.toBeNull();
    await userEvent.type(screen.getByLabelText("搜索 术语"), "Current Alias");
    expect(screen.getByText("Survivor Term")).not.toBeNull();
    expect(screen.queryByText("Loser Term")).toBeNull();

    await userEvent.clear(screen.getByLabelText("搜索 术语"));
    await userEvent.selectOptions(screen.getByLabelText("按 领域 筛选"), "ai");
    expect(screen.getByText("Survivor Term")).not.toBeNull();
    expect(screen.queryByText("Loser Term")).toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("按 领域 筛选"), "");
    await userEvent.selectOptions(screen.getByLabelText("按 主题 筛选"), "methods");
    expect(screen.getByText("Loser Term")).not.toBeNull();
    expect(screen.queryByText("Survivor Term")).toBeNull();
  });

  it("groups explicit links, detections, Sources, PDFs, and 论文推荐 Works by 术语", async () => {
    api.getEntity.mockResolvedValue({
      ...terms[0],
      content: "",
      canonical_content: "",
      related_terms: [],
      backlinks: [
        { source_entity_type: "document", source_entity_id: "note-one", source_title: "笔记 One", link_target: "Survivor Term", line: 14 },
        { source_entity_type: "term", source_entity_id: "word-term", source_title: "Word 术语", link_target: "Survivor Term", line: 7 },
      ],
      detected_mentions: [
        { id: "note-one", title: "笔记 One" },
        { id: "unlinked-note", title: "Unlinked 笔记" },
      ],
      evidence: [],
      related_documents: [],
      term_relations: [
        { entity_type: "document", entity_id: "note-one", term_id: "survivor-term", title: "笔记 One", created_from_candidate_id: "candidate-one", created_at: "2026-01-01T00:00:00Z" },
        { entity_type: "source", entity_id: "source-paper", term_id: "survivor-term", title: "Source Paper", created_from_candidate_id: "candidate-two", created_at: "2026-01-02T00:00:00Z" },
        { entity_type: "research_work", entity_id: "work-one", term_id: "survivor-term", title: "论文推荐 Work", created_from_candidate_id: "candidate-three", created_at: "2026-01-03T00:00:00Z" },
      ],
    } satisfies EntityDetail);
    const navigate = vi.fn();
    render(<TermsPage onOpen={vi.fn()} navigate={navigate} initialTab="mentions" />);

    const notes = await screen.findByRole("region", { name: "笔记" });
    expect(within(notes).getByText("笔记 One")).toBeTruthy();
    expect(within(notes).getByText("Accepted detection")).toBeTruthy();
    expect(within(notes).getByText("Explicit link")).toBeTruthy();
    expect(within(notes).getByText("Unlinked 笔记")).toBeTruthy();
    expect(within(await screen.findByRole("region", { name: "Sources & PDFs" })).getByText("Source Paper")).toBeTruthy();
    expect(within(await screen.findByRole("region", { name: "论文推荐 Works" })).getByText("论文推荐 Work")).toBeTruthy();
    expect(within(await screen.findByRole("region", { name: "Related 术语" })).getByText("Word 术语")).toBeTruthy();

    await userEvent.click(within(notes).getByRole("button", { name: /笔记 One/ }));
    await userEvent.click(within(screen.getByRole("region", { name: "Sources & PDFs" })).getByRole("button", { name: /Source Paper/ }));
    await userEvent.click(within(screen.getByRole("region", { name: "论文推荐 Works" })).getByRole("button", { name: /论文推荐 Work/ }));
    expect(navigate).toHaveBeenNthCalledWith(1, "/documents/note-one");
    expect(navigate).toHaveBeenNthCalledWith(2, "/sources/source-paper");
    expect(navigate).toHaveBeenNthCalledWith(3, "/research?work_id=work-one");
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
    expect(screen.getByText("所选 术语 的类型与深度")).not.toBeNull();
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
    expect((await screen.findByRole("status")).textContent).toContain("已将 1 个 术语 合并到 Survivor Term。");
    await waitFor(() => expect(screen.queryByText("Loser Term")).toBeNull());
  });

  it("bulk rejects only selected pending 待处理", async () => {
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "选择候选 Adaptive Token Pruning" }));
    expect(screen.queryByRole("checkbox", { name: "选择候选 Closed 候选" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "选择候选 论文推荐 Reading Phrase" })).toBeNull();
    expect(screen.getByRole("button", { name: "批量暂时移除" })).toBeTruthy();
    await userEvent.click(screen.getByText("更多操作"));
    await userEvent.click(screen.getByRole("button", { name: "批量不再推荐" }));
    await waitFor(() => expect(api.rejectTermCandidate).toHaveBeenCalledWith("candidate-new", { scope: "global" }));
    expect(api.rejectTermCandidate).toHaveBeenCalledTimes(1);
    expect(api.requestCandidateTermDraftProposal).not.toHaveBeenCalled();
  });

  it("limits batch deletion to selected 待处理 visible under the current filters", async () => {
    const pdfCandidate = candidate({
      id: "candidate-pdf",
      normalized_name: "pdf reading phrase",
      display_name: "PDF Reading Phrase",
      evidence: [{
        id: "evidence-pdf",
        candidate_id: "candidate-pdf",
        origin_type: "source",
        origin_id: "source-one",
        origin_title: "Source One",
        origin_rejected: false,
        mention: "PDF reading phrase",
        context_excerpt: "A reusable phrase from the source.",
        confidence: 0.8,
        rationale: "A useful research term.",
        discovered_at: "2026-01-04T00:00:00Z",
      }],
    });
    api.listTermCandidates.mockResolvedValue([...candidates, pdfCandidate]);
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);

    await screen.findByText("PDF Reading Phrase");
    await userEvent.click(screen.getByRole("checkbox", { name: "选择候选 Adaptive Token Pruning" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "选择候选 PDF Reading Phrase" }));
    await userEvent.click(screen.getByRole("button", { name: "笔记" }));

    expect(screen.getByText("当前筛选已选 1 项")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "批量暂时移除" }));
    const confirmation = screen.getByRole("dialog", { name: "确认删除候选" });
    expect(confirmation.textContent).toContain("Adaptive Token Pruning");
    expect(confirmation.textContent).not.toContain("PDF Reading Phrase");
    await userEvent.click(screen.getByRole("button", { name: "删除候选" }));

    await waitFor(() => expect(api.deleteTermCandidate).toHaveBeenCalledTimes(1));
    expect(api.deleteTermCandidate).toHaveBeenCalledWith("candidate-new");
  });

  it("deletes a pending 候选 without recording a rejection", async () => {
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);
    await screen.findByText("Adaptive Token Pruning");
    await userEvent.click(screen.getAllByRole("button", { name: "暂时移除", exact: true })[0]);

    expect(await screen.findByRole("dialog", { name: "确认删除候选" })).toBeTruthy();
    expect(screen.getByText(/不加入拒绝历史；以后仍可能再次被推荐/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "删除候选" }));

    await waitFor(() => expect(api.deleteTermCandidate).toHaveBeenCalledWith("candidate-new"));
    expect(api.rejectTermCandidate).not.toHaveBeenCalled();
    expect((await screen.findByRole("status")).textContent).toContain("已删除“Adaptive Token Pruning”");
  });

  it("reports partial batch deletion failures and keeps the failed 候选 selected", async () => {
    api.deleteTermCandidate.mockImplementation(async (candidateId: string) => {
      if (candidateId === "candidate-existing") throw new Error("候选 changed before deletion");
      return { deleted: true };
    });
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "选择候选 Adaptive Token Pruning" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "选择候选 Calibrated Optimizer" }));
    await userEvent.click(screen.getByRole("button", { name: "批量暂时移除" }));
    await userEvent.click(screen.getByRole("button", { name: "删除 2 项" }));

    expect((await screen.findByRole("status")).textContent).toContain("成功 1 项，失败 1 项");
    expect(screen.getByRole("status").textContent).toContain("Calibrated Optimizer：候选 changed before deletion");
    expect((screen.getByRole("checkbox", { name: "选择候选 Calibrated Optimizer" }) as HTMLInputElement).checked).toBe(true);
    expect(api.deleteTermCandidate).toHaveBeenCalledTimes(2);
    expect(api.rejectTermCandidate).not.toHaveBeenCalled();
  });

  it("filters 候选 review and links a selected 术语库 术语", async () => {
    api.acceptTermCandidate.mockResolvedValue({});
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);

    expect(await screen.findByText("Adaptive Token Pruning")).not.toBeNull();
    expect(screen.getByText("Calibrated Optimizer")).not.toBeNull();
    expect(screen.getByText("论文推荐 Reading Phrase")).not.toBeNull();
    expect(screen.queryByText("Closed 候选")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "笔记" }));
    expect(screen.queryByText("论文推荐 Reading Phrase")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "全部" }));
    await userEvent.selectOptions(screen.getByLabelText("类别"), "entity");
    expect(screen.queryByText("Adaptive Token Pruning")).toBeNull();
    expect(screen.getByText("Calibrated Optimizer")).not.toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("类别"), "");

    const pickerTrigger = screen.getByRole("button", { name: "选择其他术语" });
    await userEvent.click(pickerTrigger);
    expect(document.activeElement).toBe(screen.getByLabelText("搜索 术语"));
    await userEvent.type(screen.getByLabelText("搜索 术语"), "Loser Term");
    await userEvent.click(screen.getByRole("option", { name: /Loser Term/ }));
    await userEvent.click(screen.getByRole("button", { name: "链接到所选 术语" }));

    await waitFor(() => expect(api.acceptTermCandidate).toHaveBeenCalledWith("candidate-existing", "loser-term"));
    await waitFor(() => expect(document.activeElement).toBe(pickerTrigger));
  });

  it("reopens a 编辑中 候选's 未发布的术语修改 with its explicit 候选 context", async () => {
    const draft: Draft = {
      id: "draft-research",
      entity_type: "term",
      entity_id: "research-reading-phrase",
      base_git_revision: "a".repeat(40),
      base_content_hash: "b".repeat(64),
      content: "---\nid: research-reading-phrase\n---\n",
      revision: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    api.getDraft.mockResolvedValue(draft);
    api.listDrafts.mockResolvedValue([draft]);
    const navigate = vi.fn();
    const onOpen = vi.fn();
    render(<TermsPage onOpen={onOpen} navigate={navigate} initialTab="candidates" />);

    const openDraftButton = await screen.findByRole("button", { name: "继续编辑解释" });
    await userEvent.click(openDraftButton);

    await waitFor(() => expect(api.getDraft).toHaveBeenCalledWith("draft-research"));
    expect(await screen.findByRole("region", { name: "候选解释审核" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText("论文推荐 Reading Phrase 的 未发布的术语修改 编辑区"));
    const draftingTitle = screen.getByRole("heading", { level: 2, name: "论文推荐 Reading Phrase" });
    const draftingCard = draftingTitle.closest("article");
    expect(within(draftingCard as HTMLElement).queryByRole("button", { name: "暂时移除", exact: true })).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "关闭编辑" }));
    await waitFor(() => expect(document.activeElement).toBe(openDraftButton));
  });

  it("filters 待处理 by 笔记, PDF, 论文推荐, and 外部发现 and collapses long evidence", async () => {
    const pdfCandidate = candidate({ id: "candidate-pdf", display_name: "PDF 候选", evidence: [{ ...candidate({}).evidence[0], id: "evidence-pdf", candidate_id: "candidate-pdf", origin_type: "source", origin_id: "source-pdf", origin_title: "PDF Source" }] });
    const researchCandidate = candidate({ id: "candidate-research-work", display_name: "论文推荐 候选", evidence: [{ ...candidate({}).evidence[0], id: "evidence-research-work", candidate_id: "candidate-research-work", origin_type: "research_work", origin_id: "work-one", origin_title: "论文推荐 Work" }] });
    const webCandidate = candidate({ id: "candidate-web", display_name: "Web 候选", evidence: [{ ...candidate({}).evidence[0], id: "evidence-web", candidate_id: "candidate-web", origin_type: "external", origin_id: "https://example.com/discovery", origin_title: "外部发现" }] });
    const manyEvidenceCandidate = candidate({
      id: "candidate-many-evidence",
      display_name: "Many Evidence 候选",
      evidence: Array.from({ length: 4 }, (_, index) => ({ ...candidate({}).evidence[0], id: `evidence-many-${index}`, candidate_id: "candidate-many-evidence", origin_id: `note-${index}`, origin_title: `笔记 ${index}`, context_excerpt: `Context ${index}` })),
    });
    api.listTermCandidates.mockResolvedValue([candidate({}), pdfCandidate, researchCandidate, webCandidate, manyEvidenceCandidate]);
    const user = userEvent.setup();
    render(<TermsPage onOpen={vi.fn()} initialTab="candidates" />);

    expect(await screen.findByText("Adaptive Token Pruning")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "PDF" }));
    expect(screen.getByText("PDF 候选")).not.toBeNull();
    expect(screen.queryByText("Adaptive Token Pruning")).toBeNull();
    await user.click(screen.getByRole("button", { name: "论文推荐" }));
    expect(screen.getByText("论文推荐 候选")).not.toBeNull();
    expect(screen.queryByText("PDF 候选")).toBeNull();
    await user.click(screen.getByRole("button", { name: "外部发现" }));
    expect(screen.getByText("Web 候选")).not.toBeNull();
    expect(screen.queryByText("论文推荐 候选")).toBeNull();
    await user.click(screen.getByRole("button", { name: "全部" }));

    await screen.findByText("Many Evidence 候选");
    const evidenceCard = screen.getByText("Many Evidence 候选").closest("article");
    const evidenceSummary = within(evidenceCard as HTMLElement).getByText("来源与证据");
    const evidenceDetails = evidenceSummary.closest("details") as HTMLDetailsElement;
    expect(evidenceDetails.open).toBe(false);
    await user.click(evidenceSummary);
    expect(evidenceDetails.open).toBe(true);
    expect(screen.getByText("Context 0")).not.toBeNull();
  });

  it("creates an inline review 未发布修改 and requires an explicit action for AI generation", async () => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoViewSpy });
    scrollIntoViewSpy.mockClear();
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
    api.listDrafts.mockResolvedValue([draft]);
    api.createCandidateTermDraft.mockResolvedValue({
      candidate: candidate({ status: "drafting", draft_id: draft.id }),
      draft,
      created: true,
    });
    const onOpen = vi.fn();
    const navigate = vi.fn();
    render(<TermsPage onOpen={onOpen} navigate={navigate} initialTab="candidates" />);

    await userEvent.click((await screen.findAllByRole("button", { name: "收录为新术语" }))[0]);
    await waitFor(() => expect(api.createCandidateTermDraft).toHaveBeenCalledWith("candidate-new"));
    expect(api.requestCandidateTermDraftProposal).not.toHaveBeenCalled();
    expect(await screen.findByRole("region", { name: "候选解释审核" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Adaptive Token Pruning 的 未发布的术语修改 编辑区")));
    expect(scrollIntoViewSpy).toHaveBeenCalledWith({ block: "start", behavior: "smooth" });
    await userEvent.click(screen.getByRole("button", { name: "AI 生成双语解释" }));
    await waitFor(() => expect(api.requestCandidateTermDraftProposal).toHaveBeenCalledWith(draft.id, "candidate-new"));
    expect(navigate).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("allows Create 术语 from an active external 候选 source", async () => {
    api.listTermCandidates.mockResolvedValue([
      candidate({
        id: "candidate-external",
        normalized_name: "external evidence term",
        display_name: "External Evidence 术语",
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

    const createButton = await screen.findByRole("button", { name: "收录为新术语" });
    expect((createButton as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByText("来源与证据"));
    expect(screen.getAllByText("A bounded external excerpt.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Useful context from the external source.").length).toBeGreaterThan(0);
  });
});
