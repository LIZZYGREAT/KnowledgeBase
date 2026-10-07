import { render, screen, waitFor } from "@testing-library/react";
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

describe("Term Discovery panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getTermDiscoveryState.mockResolvedValue(state);
    api.listTermDiscoveryRuns.mockResolvedValue([]);
    api.runTermDiscovery.mockResolvedValue(run);
    api.updateTermDiscoverySettings.mockResolvedValue(state);
  });

  it("shows lane and inbox capacity and starts a manual run", async () => {
    const user = userEvent.setup();
    render(<TermDiscoveryPanel />);

    expect(await screen.findByRole("heading", { name: "Discovery" })).not.toBeNull();
    expect(screen.getByText("2 / 12")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Run Now" }));

    await waitFor(() => expect(api.runTermDiscovery).toHaveBeenCalledWith());
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("新增 2 个 Term Candidate");
  });

  it("saves lane, Focus, and source preferences", async () => {
    const user = userEvent.setup();
    render(<TermDiscoveryPanel />);

    await screen.findByRole("heading", { name: "Discovery" });
    await user.click(screen.getByRole("checkbox", { name: /Vocabulary/ }));
    await user.type(screen.getByLabelText(/Focus override/), " continual learning ");
    await user.type(screen.getByLabelText(/优先 Source ID/), " source-alpha, source-beta ");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.updateTermDiscoverySettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled_lanes: ["concept", "entity"],
        focus_override: "continual learning",
        source_preferences: ["source-alpha", "source-beta"],
      }),
    ));
  });
});
