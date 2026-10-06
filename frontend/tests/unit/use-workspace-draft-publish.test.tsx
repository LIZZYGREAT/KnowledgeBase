import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Draft, EntityDetail, EntityType } from "../../src/api";
import { useWorkspaceDraft } from "../../src/useWorkspaceDraft";

const api = vi.hoisted(() => ({
  applyProposalToDraft: vi.fn(),
  compareDraft: vi.fn(),
  createDraft: vi.fn(),
  discardDraft: vi.fn(),
  getDraft: vi.fn(),
  getEntity: vi.fn(),
  listDrafts: vi.fn(),
  publishDraft: vi.fn(),
  publishDraftsBatch: vi.fn(),
  rebaseDraft: vi.fn(),
  updateDraft: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

function makeDraft(type: EntityType, id: string): Draft {
  return {
    id: `draft-${type}`,
    entity_type: type,
    entity_id: id,
    base_git_revision: "base-revision",
    base_content_hash: "base-hash",
    content: `Draft content for ${type}`,
    revision: 1,
    created_at: "2026-10-06T00:00:00Z",
    updated_at: "2026-10-06T00:00:00Z",
  };
}

function makeEntity(type: EntityType, id: string, canonicalContent: string): EntityDetail {
  return {
    id,
    title: `Published ${type}`,
    entity_type: type,
    metadata: { type },
    content: type === "source" ? null : canonicalContent,
    canonical_content: canonicalContent,
    related_terms: [],
    backlinks: [],
    detected_mentions: [],
    evidence: [],
    related_documents: [],
  };
}

function WorkspaceDraftHarness({ type, id }: { type: EntityType; id: string }) {
  const workspace = useWorkspaceDraft(type, id);
  return <>
    <output data-testid="loading">{String(workspace.loading)}</output>
    <output data-testid="draft">{workspace.draft?.id ?? ""}</output>
    <output data-testid="canonical-entity">{workspace.canonicalEntity?.id ?? ""}</output>
    <output data-testid="canonical-content">{workspace.canonicalEntity?.canonical_content ?? ""}</output>
    <output data-testid="content">{workspace.content}</output>
    <output data-testid="load-error">{workspace.loadError}</output>
    <output data-testid="runtime-error">{workspace.error}</output>
    <output data-testid="published-revision">{workspace.publishedRevision}</output>
    <output data-testid="published-outcome">{workspace.publishedOutcome?.commitRevision ?? ""}</output>
    <button type="button" disabled={workspace.loading} onClick={() => void workspace.publish(workspace.draft?.revision ?? 1)}>
      Publish
    </button>
  </>;
}

const notFound = () => Object.assign(new Error("Entity is not in the canonical index"), { status: 404 });

describe("useWorkspaceDraft first publish", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(["document", "term", "source"] as const)(
    "replaces the initial missing canonical state after publishing a new %s",
    async (type) => {
      const user = userEvent.setup();
      const id = `new-${type}`;
      const draft = makeDraft(type, id);
      const canonicalContent = `Published content for ${type}`;
      const entity = makeEntity(type, id, canonicalContent);

      api.getEntity
        .mockRejectedValueOnce(notFound())
        .mockResolvedValueOnce(entity);
      api.listDrafts.mockResolvedValue([draft]);
      api.publishDraft.mockResolvedValue({
        draft_id: draft.id,
        entity_type: type,
        entity_id: id,
        commit_revision: `commit-${type}`,
        warnings: [],
      });

      render(<WorkspaceDraftHarness type={type} id={id} />);
      await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
      expect(screen.getByTestId("load-error").textContent).toBe("");
      expect(screen.getByTestId("draft").textContent).toBe(draft.id);

      await user.click(screen.getByRole("button", { name: "Publish" }));

      await waitFor(() => expect(screen.getByTestId("published-outcome").textContent).toBe(`commit-${type}`));
      expect(api.getEntity).toHaveBeenCalledTimes(2);
      expect(api.getEntity).toHaveBeenLastCalledWith(type, id);
      expect(screen.getByTestId("canonical-entity").textContent).toBe(id);
      expect(screen.getByTestId("canonical-content").textContent).toBe(canonicalContent);
      expect(screen.getByTestId("content").textContent).toBe(canonicalContent);
      expect(screen.getByTestId("draft").textContent).toBe("");
      expect(screen.getByTestId("published-revision").textContent).toBe(`commit-${type}`);
      expect(screen.getByTestId("load-error").textContent).toBe("");
    },
  );

  it("keeps Publish successful and clears the initial 404 when canonical hydration fails", async () => {
    const user = userEvent.setup();
    const type = "document";
    const id = "new-document";
    const draft = makeDraft(type, id);
    api.getEntity
      .mockRejectedValueOnce(notFound())
      .mockRejectedValueOnce(new Error("Canonical index temporarily unavailable"));
    api.listDrafts.mockResolvedValue([draft]);
    api.publishDraft.mockResolvedValue({
      draft_id: draft.id,
      entity_type: type,
      entity_id: id,
      commit_revision: "commit-success",
      warnings: [],
    });

    render(<WorkspaceDraftHarness type={type} id={id} />);
    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
    await user.click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(screen.getByTestId("published-outcome").textContent).toBe("commit-success"));
    expect(screen.getByTestId("published-revision").textContent).toBe("commit-success");
    expect(screen.getByTestId("draft").textContent).toBe("");
    expect(screen.getByTestId("canonical-entity").textContent).toBe("");
    expect(screen.getByTestId("content").textContent).toBe(draft.content);
    expect(screen.getByTestId("load-error").textContent).toBe("");
    expect(screen.getByTestId("runtime-error").textContent).toBe("");
  });
});
