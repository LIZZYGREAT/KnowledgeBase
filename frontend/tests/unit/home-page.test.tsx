import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "../../src/pages/HomePage";

const api = vi.hoisted(() => ({
  getTermDiscoveryState: vi.fn(),
  getUiSummary: vi.fn(),
  listResearchProfiles: vi.fn(),
  listResearchCandidates: vi.fn(),
  queueResearchRun: vi.fn(),
  listTermCandidates: vi.fn(),
  listRecentlyModified: vi.fn(),
  listUsage: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

describe("Knowledge Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getUiSummary.mockResolvedValue({
      terms_open: 2,
      terms_pending: 1,
      term_drafts: 1,
      research_new: 3,
      research_capacity: 5,
      research_profiles: 1,
      pending_imports: 1,
      maintenance: 3,
    });
    api.listTermCandidates.mockResolvedValue([
      { id: "candidate-one", status: "pending", display_name: "Attention Routing", evidence: [], discovery_assessment: { recommendation_level: "core_gap" } },
      { id: "candidate-two", status: "pending", display_name: "Other pending", evidence: [], discovery_assessment: { recommendation_level: "next" } },
    ]);
    api.listResearchProfiles.mockResolvedValue([{
      id: "profile-one",
      enabled: true,
      enabled_lens_ids: ["main"],
      paused_until: null,
      inbox: { new_count: 3, capacity: 5, remaining: 2 },
      latest_run: { status: "success", started_at: "2026-10-07T07:00:00Z", surfaced_count: 2 },
    }]);
    api.getTermDiscoveryState.mockResolvedValue({
      settings: { enabled_lanes: ["concept", "entity", "vocabulary"], focus_override: null },
      open_count: 2,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 1, entity: 1, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: { explicit: ["Vision models"], recent_topics: [], recent_domains: [] },
          knowledge: {
            established: [{ title: "Transformers", review_status: "approved", content_excerpt: "Attention mechanisms." }],
            learning: [{ title: "Diffusion" }],
            exposed: [],
            unknown: [],
          },
        },
        items: [
          { lane: "concept", outcome: "created", mention: "Historical Core Gap", assessment: { recommendation_level: "core_gap" } },
          { lane: "entity", outcome: "duplicate", mention: "Other 术语", assessment: { recommendation_level: "next" } },
        ],
      },
    });
    api.listResearchCandidates.mockResolvedValue({ candidates: [], count: 0, offset: 0, limit: 6 });
    api.queueResearchRun.mockResolvedValue({ request_id: "queued", status: "pending" });
    api.listRecentlyModified.mockResolvedValue([]);
    api.listUsage.mockResolvedValue([]);
  });

  it("puts actionable term and paper entries before details and allows manual search while paused", async () => {
    const profiles = await api.listResearchProfiles();
    api.listResearchProfiles.mockResolvedValue([{ ...profiles[0], paused_until: "2099-01-01T00:00:00Z" }]);
    const navigate = vi.fn();
    render(<HomePage onOpen={vi.fn()} navigate={navigate} />);
    const tasks = await screen.findByRole("navigation", { name: "常用任务" });
    const details = screen.getByText("学习与运行详情").closest("details");
    expect(details?.open).toBe(false);
    await userEvent.click(within(tasks).getByRole("button", { name: "查看术语库" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms");
    await userEvent.click(within(tasks).getByRole("button", { name: "发现术语" }));
    expect(navigate).toHaveBeenLastCalledWith("/terms?tab=discovery");
    await userEvent.click(screen.getByRole("button", { name: "立即查找论文" }));
    await waitFor(() => expect(api.queueResearchRun).toHaveBeenCalledWith("profile-one", expect.objectContaining({ lenses: ["main"] })));
  });

  it("places up to three evidence-backed suggestions before workload and queues the next search", async () => {
    const profiles = await api.listResearchProfiles();
    api.listResearchProfiles.mockResolvedValue([{ ...profiles[0], enabled_lens_ids: ["focus"] }]);
    api.listResearchCandidates.mockResolvedValue({ candidates: [1, 2, 3].map((number) => ({ candidate: { id: `paper-${number}`, review_overrides: {} }, work: { id: `work-${number}`, title: `Paper ${number}` }, analysis: { readiness: "high", why_relevant_zh: `Reason ${number}`, existing_relations: [] } })) });
    api.listTermCandidates.mockResolvedValue([{ id: "term", display_name: "Replay", evidence: [{ origin_rejected: false, context_excerpt: "Replay retains examples.", rationale: "Connects to the reviewed 笔记.", origin_id: "note", origin_title: "Approved 笔记" }], discovery_assessment: { why_now: "Next concept" } }]);
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);
    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    await waitFor(() => expect(featured.querySelectorAll("article").length).toBe(3));
    expect(within(featured).queryByText("Paper 3")).toBeNull();
    expect(featured.querySelectorAll(".home-recommendation-reason-summary .markdown-content")).toHaveLength(3);
    expect(within(featured).queryByRole("button", { name: "展开完整理由" })).toBeNull();
    const workload = screen.getByRole("region", { name: "现在有什么要处理？" });
    expect(featured.compareDocumentPosition(workload) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "立即查找论文" }));
    await waitFor(() => expect(api.queueResearchRun).toHaveBeenCalledWith("profile-one", { lenses: ["focus"], date_range: { mode: "incremental" } }));
  });

  it("expands and collapses long Markdown rationales in one rendered view", async () => {
    const longPaperReason = `**Paper rationale** ${"The paper fits the selected knowledge and has a distinct method. ".repeat(6)}`;
    const longTermReason = `Builds on **known 术语** ${"The source passage explains why this concept matters. ".repeat(5)}`;
    api.listResearchCandidates.mockResolvedValue({ candidates: [{
      candidate: { id: "paper-markdown", review_overrides: {} },
      work: { id: "work-markdown", title: "Markdown Paper" },
      analysis: { readiness: "high", why_relevant_zh: longPaperReason, existing_relations: [] },
    }] });
    api.listTermCandidates.mockResolvedValue([
      {
        id: "term-why-now",
        display_name: "术语 with timing",
        evidence: [{ origin_rejected: false, context_excerpt: "Reviewed passage.", rationale: "Fallback **evidence rationale**", origin_id: "note-one" }],
        discovery_assessment: { why_now: longTermReason },
      },
      {
        id: "term-evidence",
        display_name: "术语 with evidence",
        evidence: [{ origin_rejected: false, context_excerpt: "Another reviewed passage.", rationale: "Grounded in **reviewed evidence**", origin_id: "note-two" }],
        discovery_assessment: { why_now: `Grounded in **reviewed evidence** ${"The original passage supports this recommendation. ".repeat(5)}` },
      },
    ]);

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    expect(featured.querySelectorAll(".home-recommendation-reason-summary")).toHaveLength(3);
    const summaries = [...featured.querySelectorAll(".home-recommendation-reason-summary")];
    expect(summaries[0].classList.contains("is-clipped")).toBe(true);
    expect(summaries[0].querySelector("strong")?.textContent).toBe("Paper rationale");
    expect(summaries[0].textContent).toContain("has a distinct method.");
    expect(summaries[0].textContent).not.toContain("**");
    expect(featured.querySelector(".research-explanation")).toBeNull();
    expect(featured.querySelectorAll(".home-recommendation-reason-summary .markdown-content")).toHaveLength(3);
    const expandButtons = within(featured).getAllByRole("button", { name: "展开完整理由" });
    expect(expandButtons).toHaveLength(3);
    expect(expandButtons[0].getAttribute("aria-expanded")).toBe("false");
    const firstCard = summaries[0].closest("article");
    const originalText = summaries[0].textContent;
    await userEvent.click(expandButtons[0]);
    expect(summaries[0].classList.contains("is-clipped")).toBe(false);
    expect(within(firstCard as HTMLElement).getByRole("button", { name: "收起" }).getAttribute("aria-expanded")).toBe("true");
    expect(summaries[0].querySelector("strong")?.textContent).toBe("Paper rationale");
    expect(summaries[0].textContent).toBe(originalText);
    expect(summaries[0].querySelectorAll(".markdown-content")).toHaveLength(1);
    expect(featured.querySelectorAll(".home-recommendation-reason-summary .markdown-content")).toHaveLength(3);
    await userEvent.click(within(firstCard as HTMLElement).getByRole("button", { name: "收起" }));
    expect(summaries[0].classList.contains("is-clipped")).toBe(true);
    expect(within(firstCard as HTMLElement).getByRole("button", { name: "展开完整理由" }).getAttribute("aria-expanded")).toBe("false");
    expect(featured.querySelector("p p")).toBeNull();
    expect(featured.querySelector(".home-recommendation-reason-summary p p")).toBeNull();
  });

  it("renders rich short reasons without an expansion control", async () => {
    const reason = "Use [the source](https://example.com/source), `feature_vector`, and $f_\\theta(x)$ as an **important** learned representation.";
    api.listResearchCandidates.mockResolvedValue({ candidates: [{
      candidate: { id: "paper-rich-short", review_overrides: {} },
      work: { id: "work-rich-short", title: "A Short Mathematical Rationale" },
      analysis: { readiness: "high", why_relevant_zh: reason, existing_relations: [] },
    }] });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    const card = within(featured).getByRole("heading", { name: "A Short Mathematical Rationale" }).closest("article");
    expect(card).not.toBeNull();
    const summary = card?.querySelector(".home-recommendation-reason-summary");
    expect(summary?.querySelector("a")?.getAttribute("href")).toBe("https://example.com/source");
    expect(summary?.querySelector("code")?.textContent).toBe("feature_vector");
    expect(summary?.querySelector(".katex")).not.toBeNull();
    expect(summary?.querySelector("strong")?.textContent).toBe("important");
    expect(summary?.textContent).not.toContain("**important**");
    expect(summary?.textContent).not.toContain("[the source](");
    expect(summary?.textContent).not.toContain("`feature_vector`");
    expect(summary?.querySelector("p p")).toBeNull();
    expect(summary?.querySelectorAll(".markdown-content")).toHaveLength(1);
    expect(within(card as HTMLElement).queryByRole("button", { name: "展开完整理由" })).toBeNull();
  });

  it("keeps long reasons with code and block math fully visible", async () => {
    const reason = `${"This recommendation connects the reviewed source to a useful method. ".repeat(5)}\n\n~~~python\nvector = feature_vector\n~~~\n\n$$\n\\sum_{i=1}^{n} x_i = y\n$$`;
    api.listResearchCandidates.mockResolvedValue({ candidates: [{
      candidate: { id: "paper-rich-long", review_overrides: {} },
      work: { id: "work-rich-long", title: "A Long Mathematical Rationale" },
      analysis: { readiness: "high", why_relevant_zh: reason, existing_relations: [] },
    }] });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    const card = within(featured).getByRole("heading", { name: "A Long Mathematical Rationale" }).closest("article");
    const summary = card?.querySelector(".home-recommendation-reason-summary");
    expect(summary?.classList.contains("is-clipped")).toBe(false);
    expect(summary?.querySelector("pre code")?.textContent?.trim()).toBe("vector = feature_vector");
    expect(summary?.querySelector(".katex")).not.toBeNull();
    expect(summary?.querySelectorAll(".markdown-content")).toHaveLength(1);
    expect(within(card as HTMLElement).queryByRole("button", { name: "展开完整理由" })).toBeNull();
  });

  it("shows queue loading, queued feedback, errors, and working review links beside their actions", async () => {
    const navigate = vi.fn();
    const user = userEvent.setup();
    api.listResearchCandidates.mockResolvedValue({ candidates: [{
      candidate: { id: "paper-long", review_overrides: {} },
      work: { id: "work-long", title: "A Very Long Paper Title That Must Wrap On Small Screens" },
      analysis: { readiness: "high", why_relevant_zh: `Why it matters ${"based on the selected notes and reliable sources. ".repeat(7)}`, existing_relations: [] },
    }] });
    let resolveQueue!: (value: { request_id: string; status: string }) => void;
    api.queueResearchRun.mockReturnValueOnce(new Promise((resolve) => { resolveQueue = resolve; }));
    api.queueResearchRun.mockRejectedValueOnce(new Error("queue unavailable"));

    render(<HomePage onOpen={vi.fn()} navigate={navigate} />);
    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    const findButton = within(featured).getByRole("button", { name: "立即查找论文" });
    await user.click(findButton);
    const loadingButton = await within(featured).findByRole("button", { name: "正在提交检索…" });
    expect((loadingButton as HTMLButtonElement).disabled).toBe(true);
    await act(async () => resolveQueue({ request_id: "queued", status: "pending" }));
    expect(within(featured).getByRole("status").textContent).toContain("检索请求已提交");

    await user.click(within(featured).getByRole("button", { name: "立即查找论文" }));
    expect(await within(featured).findByRole("alert")).toBeTruthy();
    expect(within(featured).getByRole("alert").textContent).toContain("queue unavailable");

    await user.click(within(featured).getByRole("button", { name: "展开完整理由" }));
    expect(within(featured).getByRole("button", { name: "收起" }).getAttribute("aria-expanded")).toBe("true");
    await user.click(within(featured).getByRole("button", { name: "查看并审核论文" }));
    expect(navigate).toHaveBeenCalledWith("/research?work_id=work-long");
    await user.click(within(featured).getByRole("button", { name: "完整论文列表" }));
    expect(navigate).toHaveBeenCalledWith("/research");
  });

  it("uses a normal empty state when no supported recommendation exists", async () => {
    api.listTermCandidates.mockResolvedValue([]);
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);
    expect(await screen.findByText(/暂时没有合适的精选建议/)).toBeTruthy();
    expect(api.queueResearchRun).not.toHaveBeenCalled();
  });

  it("shows accurate workload, learning context, and agent activity", async () => {
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("2 / 8")).not.toBeNull();
    await userEvent.click(screen.getByText("其他待处理事项"));
    await userEvent.click(screen.getByText("学习与运行详情"));
    expect(screen.getByText("编辑中的术语")).not.toBeNull();
    expect(within(screen.getByRole("button", { name: /编辑中的术语/ })).getByText("1")).not.toBeNull();
    expect(screen.getByText("3 / 5")).not.toBeNull();
    expect(screen.getByText("Vision models")).not.toBeNull();
    expect(screen.getByText("Transformers")).not.toBeNull();
    expect(screen.getByText("Diffusion")).not.toBeNull();
    expect(screen.getByText("Attention Routing")).not.toBeNull();
    expect(screen.queryByText("Historical Core Gap")).toBeNull();
    expect(screen.getByText("概念发现")).not.toBeNull();
    const researchButton = await screen.findByRole("button", { name: "论文推荐" });
    const researchRow = researchButton.parentElement;
    expect(researchRow).not.toBeNull();
    expect(within(researchRow as HTMLElement).getByText("就绪")).not.toBeNull();
    expect(within(researchRow as HTMLElement).getByText(/成功 · 已推荐 2 项/)).not.toBeNull();
    expect(api.listTermCandidates).toHaveBeenCalledWith("pending");
    expect(api.listResearchProfiles).toHaveBeenCalledOnce();
    expect(api.listUsage).toHaveBeenCalledWith("recent");
    expect(api.listUsage).not.toHaveBeenCalledWith("frequent");
  });

  it("renders the critical dashboard while recent modification lookup is pending", async () => {
    let resolveRecent!: (items: never[]) => void;
    api.listRecentlyModified.mockReturnValueOnce(new Promise<never[]>((resolve) => {
      resolveRecent = resolve;
    }));

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("2 / 8")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "学习信息" })).not.toBeNull();
    expect(screen.getByText("加载中…")).not.toBeNull();
    await act(async () => resolveRecent([]));
  });

  it("routes the primary actions to their dedicated workflows", async () => {
    const navigate = vi.fn();
    const user = userEvent.setup();
    render(<HomePage onOpen={vi.fn()} navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "审阅术语" }));
    await user.click(screen.getByRole("button", { name: "打开论文推荐" }));
    await user.click(screen.getByRole("button", { name: /待检查导入/ }));

    expect(navigate).toHaveBeenNthCalledWith(1, "/terms?tab=candidates");
    expect(navigate).toHaveBeenNthCalledWith(2, "/research");
    expect(navigate).toHaveBeenNthCalledWith(3, "/library?tab=import");
  });

  it("does not present exposed or unknown 术语 as 待补充知识", async () => {
    api.listTermCandidates.mockResolvedValueOnce([]);
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept", "entity", "vocabulary"], focus_override: null },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: { explicit: [], recent_topics: [], recent_domains: [] },
          knowledge: {
            established: [],
            learning: [],
            exposed: [{ title: "Exposed 术语" }],
            unknown: [{ title: "Unknown 术语" }],
          },
        },
        items: [
          { lane: "concept", outcome: "created", mention: "Old Core Gap", assessment: { recommendation_level: "core_gap" } },
        ],
      },
    });
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    const coreGaps = screen.getByRole("heading", { name: "待补充知识" }).parentElement;
    expect(coreGaps).not.toBeNull();
    expect(within(coreGaps as HTMLElement).getByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    expect(screen.queryByText("Exposed 术语")).toBeNull();
    expect(screen.queryByText("Unknown 术语")).toBeNull();
    expect(screen.queryByText("Old Core Gap")).toBeNull();
  });

  it("shows 论文推荐 as paused when every configured profile is disabled", async () => {
    api.listResearchProfiles.mockResolvedValueOnce([{
      id: "profile-one",
      enabled: false,
      paused_until: null,
      inbox: { new_count: 0, capacity: 5, remaining: 5 },
      latest_run: null,
    }]);

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    const researchButton = await screen.findByRole("button", { name: "论文推荐" });
    const researchRow = researchButton.parentElement;
    expect(researchRow).not.toBeNull();
    expect(await within(researchRow as HTMLElement).findByText("已暂停")).not.toBeNull();
    expect(within(researchRow as HTMLElement).getByText("尚无运行记录")).not.toBeNull();
  });

  it("shows 论文推荐 as paused when all active profile inboxes are full", async () => {
    api.listResearchProfiles.mockResolvedValueOnce([{
      id: "profile-one",
      enabled: true,
      paused_until: null,
      inbox: { new_count: 5, capacity: 5, remaining: 0 },
      latest_run: null,
    }]);

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("已暂停 · 待看论文已满")).not.toBeNull();
  });

  it("uses the effective 检索主题 stored in the 发现术语 run", async () => {
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept"], focus_override: "Current override" },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          effective_focus: ["iCaRL", "Herding", "Continual Learning"],
          focus: {
            explicit: ["Continual Learning"],
            recent_terms: [{ title: "iCaRL" }, { title: "Herding" }],
            recent_topics: [],
            recent_domains: [],
          },
          knowledge: { established: [], learning: [], exposed: [], unknown: [] },
        },
        items: [],
      },
    });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    await screen.findByText("iCaRL");
    const focus = screen.getByRole("heading", { name: "当前学习方向" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "iCaRL",
      "Herding",
      "Continual Learning",
    ]);
    expect(screen.queryByText("Current override")).toBeNull();
  });

  it("reconstructs legacy 检索主题 from override, recent context, then explicit profile", async () => {
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept"], focus_override: "Current override" },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: {
            explicit: ["Continual Learning"],
            recent_terms: [{ title: "iCaRL" }],
            recent_topics: ["Class-Incremental Learning"],
            recent_domains: ["Machine Learning"],
          },
          knowledge: { established: [], learning: [], exposed: [], unknown: [] },
        },
        items: [],
      },
    });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    await screen.findByText("iCaRL");
    const focus = screen.getByRole("heading", { name: "当前学习方向" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Current override",
      "iCaRL",
      "Class-Incremental Learning",
      "Machine Learning",
      "Continual Learning",
    ]);
  });
});
