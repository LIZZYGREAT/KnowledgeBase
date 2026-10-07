import { afterEach, describe, expect, it, vi } from "vitest";
import { getUiSummary, runTermDiscovery } from "../../src/api";

describe("workload summary refresh events", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("dispatches after a successful mutation and not after a read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        terms_open: 0,
        terms_pending: 0,
        term_drafts: 0,
        research_new: 0,
        research_capacity: 0,
        research_profiles: 0,
        pending_imports: 0,
        maintenance: 0,
      }),
    } as Response));
    const dispatch = vi.spyOn(window, "dispatchEvent");

    await getUiSummary();
    expect(dispatch).not.toHaveBeenCalled();

    await runTermDiscovery();
    expect(dispatch).toHaveBeenCalledOnce();
    expect(dispatch.mock.calls[0][0].type).toBe("kb:workload-changed");
  });
});
