import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TermDiscoveryPanel } from "../../src/pages/TermDiscoveryPanel";

const api = vi.hoisted(() => ({
  getTermDiscoveryState: vi.fn(),
  listTermDiscoveryRuns: vi.fn(),
  runTermDiscovery: vi.fn(),
  updateTermDiscoverySettings: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

const state = {
  settings: {
    enabled_lanes: ["concept", "entity", "vocabulary"] as Array<"concept" | "entity" | "vocabulary">,
    daily_max_new: 5,
    lane_capacities: { concept: 5, entity: 4, vocabulary: 6 },
    source_preferences: [],
    focus_override: null,
  },
  open_count: 2,
  global_capacity: 12,
  daily_remaining: 5,
  lane_open: { concept: 1, entity: 1, vocabulary: 0 },
  lane_capacity: { concept: 5, entity: 4, vocabulary: 6 },
  last_run: null,
};

const run = {
  id: "run-one",
  trigger: "manual" as const,
  status: "success" as const,
  snapshot: {},
  lane_budgets: { concept: 2, entity: 2, vocabulary: 1 },
  raw_counts: { concept: 1, entity: 1, vocabulary: 0 },
  filtered_counts: { concept: 0, entity: 0, vocabulary: 0 },
  candidate_count: 2,
  started_at: "2026-10-07T08:00:00+00:00",
  finished_at: "2026-10-07T08:00:05+00:00",
  error_summary: null,
  items: [],
};

describe("发现术语 panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getTermDiscoveryState.mockResolvedValue(state);
    api.listTermDiscoveryRuns.mockResolvedValue([]);
    api.runTermDiscovery.mockResolvedValue(run);
    api.updateTermDiscoverySettings.mockResolvedValue(state);
  });

  it("shows failed discovery clearly and keeps advanced configuration collapsed", async () => {
    api.runTermDiscovery.mockResolvedValue({ ...run, status: "failed", candidate_count: 0 });
    render(<TermDiscoveryPanel />);
    await screen.findByRole("heading", { name: "发现术语" });
    expect(screen.getByText("高级设置").closest("details")?.open).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "立即发现" }));
    expect((await screen.findByRole("status")).textContent).toContain("发现失败");
  });

  it("shows lane and inbox capacity and starts a manual run", async () => {
    const user = userEvent.setup();
    render(<TermDiscoveryPanel />);

    expect(await screen.findByRole("heading", { name: "发现术语" })).not.toBeNull();
    expect(screen.getByText("2 / 12")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "立即发现" }));

    await waitFor(() => expect(api.runTermDiscovery).toHaveBeenCalledWith());
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("新增 2 个待处理术语");
  });

  it("localizes discovery history statuses, counts, outcomes, and readiness", async () => {
    api.listTermDiscoveryRuns.mockResolvedValue([{
      ...run,
      status: "partial",
      items: [{
        id: "item-one",
        run_id: "run-one",
        lane: "concept",
        source_id: "note-one",
        mention: "Attention Routing",
        outcome: "created",
        candidate_id: "candidate-one",
        assessment: {
          readiness: "high",
          recommendation_level: "core_gap",
          known_prerequisites: [],
          missing_prerequisites: [],
          why_now: "适合当前学习阶段。",
        },
        rationale: "来自已审核笔记。",
        context_excerpt: "Attention routes retrieved memories.",
      }],
    }]);
    render(<TermDiscoveryPanel />);

    expect(await screen.findByText("1 次运行")).not.toBeNull();
    expect(screen.getByText("部分完成")).not.toBeNull();
    const runSummary = screen.getByText("新增 2 个");
    expect(runSummary).not.toBeNull();
    const runDetails = runSummary.closest("details") as HTMLDetailsElement;
    fireEvent.click(runSummary.closest("summary") as HTMLElement);
    expect(await within(runDetails).findByText("已加入待处理")).not.toBeNull();
    expect(within(runDetails).getByText("准备度：高")).not.toBeNull();
    expect(within(runDetails).getByText("概念")).not.toBeNull();
    expect(screen.queryByText(/\bruns\b|\bnew\b|\breadiness\b/)).toBeNull();
  });

  it("saves lane, 检索主题, and source preferences", async () => {
    const user = userEvent.setup();
    render(<TermDiscoveryPanel />);

    await screen.findByRole("heading", { name: "发现术语" });
    await user.click(screen.getByRole("checkbox", { name: /专业词汇/ }));
    await user.click(screen.getByText("高级设置"));
    await user.type(screen.getByLabelText(/自定义研究方向/), " continual learning ");
    await user.type(screen.getByLabelText(/优先文献标识/), " source-alpha, source-beta ");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(api.updateTermDiscoverySettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled_lanes: ["concept", "entity"],
        focus_override: "continual learning",
        source_preferences: ["source-alpha", "source-beta"],
      }),
    ));
  });
});
