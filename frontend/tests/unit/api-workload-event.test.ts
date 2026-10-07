import { afterEach, describe, expect, it, vi } from "vitest";
import {
  acceptTermCandidate,
  createCandidateTermDraft,
  createImport,
  createImportDraft,
  dismissResearchCandidate,
  getUiSummary,
  listTermCandidates,
  previewTermMerge,
  recordDocumentOpen,
  recordSearchClick,
  rejectTermCandidate,
  runTermDiscovery,
  shortlistResearchCandidate,
  updateImportItem,
} from "../../src/api";

describe("workload summary refresh events", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not dispatch for reads, usage events, or merge previews", async () => {
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
    await listTermCandidates("pending");
    await recordDocumentOpen("doc-one");
    await recordSearchClick("doc-one");
    await previewTermMerge({ survivor_term_id: "winner", loser_term_ids: ["loser"], final_title: "Winner" });
    expect(dispatch).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith("/api/terms/candidates?status=pending", expect.any(Object));
  });

  it("dispatches only for mutations that can change workload counts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as Response));
    const dispatch = vi.spyOn(window, "dispatchEvent");

    await rejectTermCandidate("candidate-one", { scope: "global" });
    await acceptTermCandidate("candidate-two", "term-one");
    await createCandidateTermDraft("candidate-three");
    await shortlistResearchCandidate("research-candidate");
    await dismissResearchCandidate("research-candidate-two");
    await createImport(["incoming.md"], "standard");
    await createImportDraft("import-item");
    await updateImportItem("import-item-two", "---\ntitle: Note\n---\nBody");
    await runTermDiscovery();

    expect(dispatch).toHaveBeenCalledTimes(9);
    expect(dispatch.mock.calls.every(([event]) => event.type === "kb:workload-changed")).toBe(true);
  });
});
