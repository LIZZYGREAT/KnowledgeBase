import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "../../src/pages/HomePage";

const api = vi.hoisted(() => ({
  getTermDiscoveryState: vi.fn(),
  getUiSummary: vi.fn(),
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
            established: [{ title: "Transformers" }],
            learning: [{ title: "Diffusion" }],
            exposed: [],
            unknown: [],
          },
        },
        items: [
          { lane: "concept", outcome: "created", mention: "Attention Routing", assessment: { recommendation_level: "core_gap" } },
          { lane: "entity", outcome: "duplicate", mention: "Other Term", assessment: { recommendation_level: "next" } },
        ],
      },
    });
    api.listRecentlyModified.mockResolvedValue([]);
    api.listUsage.mockResolvedValue([]);
  });

  it("shows accurate workload, learning context, and agent activity", async () => {
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("2 / 8")).not.toBeNull();
    expect(screen.getByText("Term Drafts")).not.toBeNull();
    expect(within(screen.getByRole("button", { name: /Term Drafts/ })).getByText("1")).not.toBeNull();
    expect(screen.getByText("3 / 5")).not.toBeNull();
    expect(screen.getByText("Vision models")).not.toBeNull();
    expect(screen.getByText("Transformers")).not.toBeNull();
    expect(screen.getByText("Diffusion")).not.toBeNull();
    expect(screen.getByText("Attention Routing")).not.toBeNull();
    expect(screen.getByText("Concept Discovery")).not.toBeNull();
    expect(screen.getByText("Research")).not.toBeNull();
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
    expect(screen.getByRole("heading", { name: "Learning Context" })).not.toBeNull();
    expect(screen.getByText("加载中…")).not.toBeNull();
    await act(async () => resolveRecent([]));
  });

  it("routes the primary actions to their dedicated workflows", async () => {
    const navigate = vi.fn();
    const user = userEvent.setup();
    render(<HomePage onOpen={vi.fn()} navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "Review Terms" }));
    await user.click(screen.getByRole("button", { name: "Open Research" }));
    await user.click(screen.getByRole("button", { name: /Pending Imports/ }));

    expect(navigate).toHaveBeenNthCalledWith(1, "/terms?tab=candidates");
    expect(navigate).toHaveBeenNthCalledWith(2, "/research");
    expect(navigate).toHaveBeenNthCalledWith(3, "/library?tab=import");
  });

  it("does not present exposed or unknown Terms as Core Gaps", async () => {
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
            exposed: [{ title: "Exposed Term" }],
            unknown: [{ title: "Unknown Term" }],
          },
        },
        items: [],
      },
    });
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    const coreGaps = screen.getByRole("heading", { name: "Core Gaps" }).parentElement;
    expect(coreGaps).not.toBeNull();
    expect(within(coreGaps as HTMLElement).getByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    expect(screen.queryByText("Exposed Term")).toBeNull();
    expect(screen.queryByText("Unknown Term")).toBeNull();
  });

  it("uses the effective Focus stored in the Discovery run", async () => {
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
    const focus = screen.getByRole("heading", { name: "Current Focus" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "iCaRL",
      "Herding",
      "Continual Learning",
    ]);
    expect(screen.queryByText("Current override")).toBeNull();
  });

  it("reconstructs legacy Focus from override, recent context, then explicit profile", async () => {
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
    const focus = screen.getByRole("heading", { name: "Current Focus" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Current override",
      "iCaRL",
      "Class-Incremental Learning",
      "Machine Learning",
      "Continual Learning",
    ]);
  });
});
