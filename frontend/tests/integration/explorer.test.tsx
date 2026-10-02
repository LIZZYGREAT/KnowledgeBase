import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { parse } from "yaml";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorerPage } from "../../src/Explorer";
import { WorkspacePage } from "../../src/Workspace";
import type { Collection, CollectionSummary, Draft, EntitySummary } from "../../src/api";

const api = vi.hoisted(() => ({
  listCollections: vi.fn(),
  getCollection: vi.fn(),
  listDrafts: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  discardDraft: vi.fn(),
  compareDraft: vi.fn(),
  publishDraftsBatch: vi.fn(),
  listAllEntities: vi.fn(),
  listAllUnfiledDocuments: vi.fn(),
  listUsage: vi.fn(),
  createBlankDocument: vi.fn(),
  getEntity: vi.fn(),
  getCollectionNavigation: vi.fn(),
  preflightDraft: vi.fn(),
  listProposals: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

const collectionId = "study-path";
const document: EntitySummary = {
  id: "orphan-note",
  title: "Orphan note",
  entity_type: "document",
  metadata: { type: "learning-note", review: { human: { status: "approved" } } },
};

function makeCollection(nodes: Collection["nodes"] = []): Collection {
  return {
    id: collectionId,
    title: "Study Path",
    description: "A test path",
    status: "active",
    position: 0,
    nodes,
  };
}

function makeSummary(): CollectionSummary {
  return {
    id: collectionId,
    title: "Study Path",
    description: "A test path",
    status: "active",
    position: 0,
    node_count: 1,
    entity_count: 0,
    document_count: 0,
  };
}

let canonical: Collection;
let drafts: Draft[];
let draftSequence: number;
let collectionConflict: boolean;
let createdNoteId = "";

function makeDraft(entityType: Draft["entity_type"], entityId: string, content: string): Draft {
  draftSequence += 1;
  return {
    id: `draft-${draftSequence}`,
    entity_type: entityType,
    entity_id: entityId,
    base_git_revision: "base-revision",
    base_content_hash: "base-hash",
    content,
    revision: 1,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
  };
}

function installApiBehavior() {
  api.listCollections.mockImplementation(async (status: "active" | "archived") => status === "active" ? [makeSummary()] : []);
  api.getCollection.mockImplementation(async () => ({ ...canonical, nodes: structuredClone(canonical.nodes) }));
  api.listDrafts.mockImplementation(async (type: string, id: string) => drafts.filter((draft) => draft.entity_type === type && draft.entity_id === id));
  api.createDraft.mockImplementation(async (type: Draft["entity_type"], id: string, content: string) => {
    const draft = makeDraft(type, id, content);
    drafts.push(draft);
    return draft;
  });
  api.updateDraft.mockImplementation(async (id: string, content: string, revision: number) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw new Error("Draft not found");
    Object.assign(draft, { content, revision: revision + 1 });
    return { ...draft };
  });
  api.discardDraft.mockImplementation(async (id: string) => {
    drafts = drafts.filter((draft) => draft.id !== id);
  });
  api.compareDraft.mockImplementation(async (id: string) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw new Error("Draft not found");
    return {
      draft: { ...draft },
      base_content: "title: Base Collection\n",
      current_content: "title: Current Collection\n",
      current_git_revision: "current-revision",
      current_content_hash: collectionConflict ? "changed-hash" : "base-hash",
      canonical_changed: collectionConflict,
    };
  });
  api.publishDraftsBatch.mockImplementation(async (ids: string[]) => {
    for (const id of ids) {
      const draft = drafts.find((item) => item.id === id);
      if (draft?.entity_type === "collection") {
        const next = parse(draft.content) as Collection;
        canonical = { ...canonical, ...next };
      }
    }
    return { results: [], commit_revision: "batch-revision", warnings: [] };
  });
  api.listAllEntities.mockImplementation(async (type: string) => type === "document" ? [document] : []);
  api.listAllUnfiledDocuments.mockResolvedValue([document]);
  api.listUsage.mockResolvedValue([]);
  api.createBlankDocument.mockImplementation(async (title: string, documentType: string, id?: string) => {
    const entityId = id ?? "new-note-12345678";
    createdNoteId = entityId;
    const content = `---\ntitle: ${title}\ntype: ${documentType}\nreview:\n  human:\n    status: unreviewed\nmaintenance:\n  status: current\n---\n`;
    const draft = makeDraft("document", entityId, content);
    drafts.push(draft);
    return draft;
  });
  api.getEntity.mockImplementation(async (type: string, id: string) => {
    const draft = drafts.find((item) => item.entity_type === type && item.entity_id === id);
    if (draft) throw Object.assign(new Error("Not found"), { status: 404 });
    throw Object.assign(new Error("Not found"), { status: 404 });
  });
  api.getCollectionNavigation.mockResolvedValue(null);
  api.preflightDraft.mockImplementation(async (id: string) => ({ draft_id: id, valid: true, conflict: false, errors: [], warnings: [] }));
  api.listProposals.mockResolvedValue([]);
}

function renderExplorer(navigate = vi.fn()) {
  return { navigate, ...render(<ExplorerPage onOpen={vi.fn()} navigate={navigate} />) };
}

function RouteHarness() {
  const [path, setPath] = useState(`/explorer?collection=${collectionId}`);
  const url = new URL(path, window.location.origin);
  if (url.pathname === "/explorer") return <ExplorerPage onOpen={() => undefined} navigate={setPath} />;
  const id = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
  const activeCollectionId = url.searchParams.get("collection") ?? undefined;
  const batchCollectionId = url.searchParams.get("publishAll") === "1" ? activeCollectionId : undefined;
  return <WorkspacePage type="document" id={id} navigate={setPath} collectionId={activeCollectionId} batchCollectionId={batchCollectionId} initialMode="edit" />;
}

describe("Explorer React integration", () => {
  beforeEach(() => {
    canonical = makeCollection([{ id: "section-notes", kind: "section", title: "Notes", children: [] }]);
    drafts = [];
    draftSequence = 0;
    collectionConflict = false;
    createdNoteId = "";
    vi.clearAllMocks();
    installApiBehavior();
  });

  it("drags an existing Document into a Collection, autosaves its Draft, and publishes it", async () => {
    const user = userEvent.setup();
    renderExplorer();
    await screen.findByRole("heading", { name: "Study Path" });
    const editStructure = await screen.findByRole("button", { name: "编辑结构" });
    await waitFor(() => expect((editStructure as HTMLButtonElement).disabled).toBe(false));
    await user.click(editStructure);
    await user.click(screen.getByRole("button", { name: /All Documents/ }));

    const row = (await screen.findByText("Orphan note")).closest(".explorer-virtual-row");
    expect(row).not.toBeNull();
    const values = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      setData: (key: string, value: string) => values.set(key, value),
      getData: (key: string) => values.get(key) ?? "",
    };
    fireEvent.dragStart(row!, { dataTransfer });
    fireEvent.drop(screen.getByRole("tree"), { dataTransfer });

    await waitFor(() => expect(api.createDraft).toHaveBeenCalledOnce(), { timeout: 2500 });
    expect(api.createDraft.mock.calls[0][0]).toBe("collection");
    expect(api.createDraft.mock.calls[0][2]).toContain("orphan-note");
    await user.click(await screen.findByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    expect(api.publishDraftsBatch.mock.calls[0][0]).toEqual(["draft-1"]);
  });

  it("recovers a conflicted Collection Draft by discarding it and reloading Canonical", async () => {
    const staleDraft = makeDraft("collection", collectionId, `id: ${collectionId}\ntitle: Stale\nnodes: []\n`);
    drafts.push(staleDraft);
    collectionConflict = true;
    renderExplorer();

    await screen.findByRole("heading", { name: "解决 Collection 冲突" });
    await userEvent.setup().click(screen.getByRole("button", { name: "放弃 Draft 并载入 Canonical" }));
    await waitFor(() => expect(api.discardDraft).toHaveBeenCalledWith(staleDraft.id, staleDraft.revision));
    expect(await screen.findByRole("heading", { name: "Study Path" })).toBeTruthy();
  });

  it("creates a note inside a Collection and batch-publishes both Drafts in one Publisher call", async () => {
    const user = userEvent.setup();
    render(<RouteHarness />);
    await screen.findByRole("heading", { name: "Study Path" });
    const editStructure = await screen.findByRole("button", { name: "编辑结构" });
    await waitFor(() => expect((editStructure as HTMLButtonElement).disabled).toBe(false));
    await user.click(editStructure);
    await user.click(screen.getByRole("button", { name: "在 Notes 中新建笔记" }));
    await user.type(screen.getByRole("textbox", { name: "笔记标题" }), "Nested note");
    await user.click(screen.getByRole("button", { name: "创建 Draft 并编辑" }));

    await screen.findByRole("heading", { name: `编辑 ${createdNoteId}` });
    await user.click(screen.getByRole("button", { name: "Publish All" }));
    const batchPublish = await screen.findByRole("button", { name: "Publish All · 一个 Git 提交" });
    await waitFor(() => expect((batchPublish as HTMLButtonElement).disabled).toBe(false));
    await user.click(batchPublish);

    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    expect(api.publishDraftsBatch.mock.calls[0][0]).toHaveLength(2);
    expect(api.publishDraftsBatch.mock.calls[0][0]).toContain("draft-1");
    expect(api.publishDraftsBatch.mock.calls[0][0]).toContain("draft-2");
  });
});
