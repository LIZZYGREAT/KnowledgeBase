import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { parse } from "yaml";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorerPage } from "../../src/Explorer";
import { WorkspacePage } from "../../src/Workspace";
import { collectionToDraft, serializeCollectionDraft } from "../../src/collectionDraftModel";
import type { Collection, CollectionSummary, Draft, EntitySummary } from "../../src/api";

const api = vi.hoisted(() => ({
  listCollections: vi.fn(),
  getCollection: vi.fn(),
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
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

function makeCollection(nodes: Collection["nodes"] = [], id = collectionId, title = "Study Path", position = 0): Collection {
  return {
    id,
    title,
    description: "A test path",
    status: "active",
    position,
    nodes,
  };
}

function makeSummary(id = collectionId, title = "Study Path", position = 0): CollectionSummary {
  return {
    id,
    title,
    description: "A test path",
    status: "active",
    position,
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
  api.getDraft.mockImplementation(async (id: string) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw Object.assign(new Error("Draft not found"), { status: 404 });
    return { ...draft };
  });
  api.createDraft.mockImplementation(async (type: Draft["entity_type"], id: string, content: string) => {
    const draft = makeDraft(type, id, content);
    drafts.push(draft);
    return { draft, created: true };
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
      base_content: canonical ? serializeCollectionDraft(collectionToDraft(canonical)) : "",
      current_content: canonical ? serializeCollectionDraft(collectionToDraft(canonical)) : "",
      current_git_revision: "current-revision",
      current_content_hash: collectionConflict ? "changed-hash" : "base-hash",
      canonical_changed: collectionConflict,
    };
  });
  api.publishDraftsBatch.mockImplementation(async (draftsToPublish: Array<{ draft_id: string; expected_revision: number }>) => {
    for (const expected of draftsToPublish) {
      const draft = drafts.find((item) => item.id === expected.draft_id);
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
  return <WorkspacePage type="document" id={id} navigate={setPath} collectionId={activeCollectionId} batchCollectionId={batchCollectionId} />;
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
    await screen.findByRole("heading", { name: "发布变更" });
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    expect(api.publishDraftsBatch.mock.calls[0][0]).toEqual([
      { draft_id: "draft-1", expected_revision: 1 },
    ]);
  });

  it("keeps copy errors in the copy flow and closes with a success notice after retry", async () => {
    const user = userEvent.setup();
    const targetId = "target-path";
    canonical = makeCollection([{
      id: "section-notes",
      kind: "section",
      title: "Notes",
      children: [{
        id: "entity-orphan-note",
        kind: "entity",
        entity_type: "document",
        entity_id: document.id,
        title: document.title,
        progress: null,
      }],
    }]);
    api.listCollections.mockImplementation(async (status: "active" | "archived") => status === "active"
      ? [makeSummary(), makeSummary(targetId, "Target Path", 1)]
      : []);
    api.getCollection.mockImplementation(async (id: string) => id === targetId
      ? makeCollection([], targetId, "Target Path", 1)
      : ({ ...canonical, nodes: structuredClone(canonical.nodes) }));
    api.createDraft.mockRejectedValueOnce(new Error("Target Collection is unavailable"));

    renderExplorer();
    await screen.findByRole("heading", { name: "Study Path" });
    const editStructure = await screen.findByRole("button", { name: "编辑结构" });
    await waitFor(() => expect((editStructure as HTMLButtonElement).disabled).toBe(false));
    await user.click(editStructure);
    await user.click(await screen.findByRole("button", { name: "复制 Orphan note 到其他 Collection" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "目标 Collection" }), targetId);
    await user.click(screen.getByRole("button", { name: "复制引用" }));
    await within(screen.getByRole("dialog", { name: "Copy to Collection" })).findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("Target Collection is unavailable");
    expect(screen.queryByText("Target Collection is unavailable")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "复制引用" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Copy to Collection" })).toBeNull());
    expect((await screen.findByRole("status")).textContent).toContain("已将“Orphan note”复制到 Target Path 的 Collection Draft。");
    expect(api.createDraft).toHaveBeenCalledTimes(2);
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

  it("separates Collection Runtime Draft conflicts and keeps local YAML using the latest revision", async () => {
    const user = userEvent.setup();
    const existing = makeDraft("collection", collectionId, serializeCollectionDraft(collectionToDraft(canonical)));
    drafts.push(existing);
    const otherTabContent = `id: ${collectionId}\ntitle: Other tab\nnodes: []\n`;
    api.updateDraft.mockImplementationOnce(async () => {
      Object.assign(existing, { content: otherTabContent, revision: 2 });
      throw Object.assign(new Error("Draft revision changed"), {
        status: 409,
        code: "draft_revision_conflict",
        expected_revision: 1,
        current_revision: 2,
      });
    });
    renderExplorer();
    await screen.findByRole("heading", { name: "Study Path" });
    const editStructure = await screen.findByRole("button", { name: "编辑结构" });
    await waitFor(() => expect((editStructure as HTMLButtonElement).disabled).toBe(false));
    await user.click(editStructure);
    await user.click(screen.getByRole("button", { name: /All Documents/ }));
    const row = (await screen.findByText("Orphan note")).closest(".explorer-virtual-row");
    const values = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      setData: (key: string, value: string) => values.set(key, value),
      getData: (key: string) => values.get(key) ?? "",
    };
    fireEvent.dragStart(row!, { dataTransfer });
    fireEvent.drop(screen.getByRole("tree"), { dataTransfer });

    await screen.findByRole("heading", { name: "Collection Draft 内容冲突" });
    expect(screen.getByText(/Other tab/)).toBeTruthy();
    expect(api.compareDraft).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "保留本地并保存" }));

    await waitFor(() => expect(api.updateDraft).toHaveBeenLastCalledWith(
      existing.id,
      expect.stringContaining("orphan-note"),
      2,
    ));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Collection Draft 内容冲突" })).toBeNull());
  });

  it("reviews Collection YAML before publishing and binds confirmation to the reviewed revision", async () => {
    const user = userEvent.setup();
    const collectionDraft = makeDraft("collection", collectionId, [
      "schema_version: 1",
      `id: ${collectionId}`,
      "title: Renamed Study Path",
      "description: Reviewed description",
      "status: archived",
      "position: 3",
      "nodes:",
      "  - id: section-reading",
      "    kind: section",
      "    title: Reading",
      "    children:",
      "      - id: reference-one",
      "        kind: entity",
      "        entity_type: document",
      "        entity_id: orphan-note",
    ].join("\n") + "\n");
    collectionDraft.revision = 5;
    drafts.push(collectionDraft);
    api.publishDraftsBatch.mockImplementationOnce(async (expectations: Array<{ draft_id: string; expected_revision: number }>) => {
      const expected = expectations[0];
      if (expected.expected_revision !== collectionDraft.revision) {
        throw Object.assign(new Error("Draft changed after review."), { status: 409 });
      }
      return { results: [], commit_revision: "reviewed-revision", warnings: [] };
    });
    const { container } = renderExplorer();

    await user.click(await screen.findByRole("button", { name: "Publish" }));
    await screen.findByRole("heading", { name: "发布变更" });
    expect(await screen.findByText(/Collection 变化：Study Path：标题、描述、状态、排序位置、分区结构、Entity 引用/)).toBeTruthy();
    const showDiff = screen.getByRole("button", { name: "查看完整差异" });
    await user.click(showDiff);
    expect(container.querySelector(".publish-full-diff")?.textContent).toContain("section-reading");
    expect(screen.getByText(/Draft revision 5/)).toBeTruthy();

    collectionDraft.revision = 6;
    collectionDraft.content = collectionDraft.content.replace("Reviewed description", "Changed after review");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    await within(screen.getByRole("dialog", { name: "发布变更" })).findByRole("alert");
    expect(api.publishDraftsBatch).toHaveBeenNthCalledWith(1, [{ draft_id: collectionDraft.id, expected_revision: 5 }]);

    await user.click(screen.getByRole("button", { name: "重新检查" }));
    await waitFor(() => expect(screen.getByText(/Draft revision 6/)).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledTimes(2));
    expect(api.publishDraftsBatch).toHaveBeenNthCalledWith(2, [{ draft_id: collectionDraft.id, expected_revision: 6 }]);
  });

  it("keeps Collection reorders in position Drafts until one organization publish", async () => {
    const user = userEvent.setup();
    const canonicalById = new Map<string, Collection>([
      [collectionId, makeCollection([{ id: "section-notes", kind: "section", title: "Notes", children: [] }])],
      ["middle-path", makeCollection([], "middle-path", "Middle Path", 1)],
      ["last-path", makeCollection([], "last-path", "Last Path", 2)],
    ]);
    window.localStorage.removeItem("knowledgebase.explorer-preferences");
    api.listCollections.mockImplementation(async (status: "active" | "archived") => status === "active"
      ? [...canonicalById.values()].map((item) => ({
        ...makeSummary(item.id, item.title, item.position),
      })).sort((left, right) => left.position - right.position)
      : []);
    api.getCollection.mockImplementation(async (id: string) => {
      const item = canonicalById.get(id);
      if (!item) throw new Error("Collection not found");
      return { ...item, nodes: structuredClone(item.nodes) };
    });
    api.publishDraftsBatch.mockImplementation(async (expectations: Array<{ draft_id: string; expected_revision: number }>) => {
      for (const expected of expectations) {
        const draft = drafts.find((item) => item.id === expected.draft_id);
        if (!draft || draft.revision !== expected.expected_revision) throw Object.assign(new Error("Stale revision"), { status: 409 });
        const current = canonicalById.get(draft.entity_id)!;
        canonicalById.set(draft.entity_id, { ...current, ...parse(draft.content) });
      }
      return { results: [], commit_revision: "organization-revision", warnings: [] };
    });
    renderExplorer();

    await screen.findByRole("heading", { name: "Study Path" });
    const moveDown = await screen.findByRole("button", { name: "下移此 Collection 并暂存排序" });
    await waitFor(() => expect((moveDown as HTMLButtonElement).disabled).toBe(false));
    await user.click(moveDown);
    await screen.findByText("2 个未发布的 Collection 排序修改");
    await waitFor(() => expect((screen.getByRole("button", { name: "下移此 Collection 并暂存排序" }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "下移此 Collection 并暂存排序" }));
    await screen.findByText("3 个未发布的 Collection 排序修改");

    expect(api.publishDraftsBatch).not.toHaveBeenCalled();
    expect(drafts.filter((draft) => draft.entity_type === "collection")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Publish Organization Changes" }));

    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    const submitted = api.publishDraftsBatch.mock.calls[0][0] as Array<{ draft_id: string; expected_revision: number }>;
    expect(submitted).toHaveLength(3);
    for (const expected of submitted) {
      const draft = drafts.find((item) => item.id === expected.draft_id)!;
      expect(expected.expected_revision).toBe(draft.revision);
    }
    await waitFor(() => expect(screen.queryByText(/个未发布的 Collection 排序修改/)).toBeNull());
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

    await screen.findByRole("heading", { name: "Nested note" });
    await user.click(screen.getByRole("button", { name: "Publish All" }));
    const batchPublish = await screen.findByRole("button", { name: "Publish All · 一个 Git 提交" });
    await waitFor(() => expect((batchPublish as HTMLButtonElement).disabled).toBe(false));
    await user.click(batchPublish);

    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    expect(api.publishDraftsBatch.mock.calls[0][0]).toHaveLength(2);
    expect(api.publishDraftsBatch.mock.calls[0][0].map((item) => item.draft_id)).toContain("draft-1");
    expect(api.publishDraftsBatch.mock.calls[0][0].map((item) => item.draft_id)).toContain("draft-2");
  });

  it("discards a new note while preserving earlier Collection Draft changes", async () => {
    const user = userEvent.setup();
    const previousCollectionDraft = makeDraft(
      "collection",
      collectionId,
      "schema_version: 1\nid: study-path\ntitle: Study Path\n"
        + "description: Previously edited description\nstatus: active\nposition: 0\n"
        + "nodes:\n  - id: section-notes\n    kind: section\n"
        + "    title: Renamed Notes\n    children: []\n",
    );
    drafts.push(previousCollectionDraft);
    const confirmation = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<RouteHarness />);

    await screen.findByRole("heading", { name: "Study Path" });
    const editStructure = await screen.findByRole("button", { name: "编辑结构" });
    await waitFor(() => expect((editStructure as HTMLButtonElement).disabled).toBe(false));
    await user.click(editStructure);
    await user.click(screen.getByRole("button", { name: "在 Renamed Notes 中新建笔记" }));
    await user.type(screen.getByRole("textbox", { name: "笔记标题" }), "Temporary note");
    await user.click(screen.getByRole("button", { name: "创建 Draft 并编辑" }));
    await screen.findByRole("heading", { name: "Temporary note" });
    const createdDocumentDraft = drafts.find((draft) => draft.entity_type === "document" && draft.entity_id === createdNoteId);
    expect(createdDocumentDraft).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "丢弃笔记并撤销引用" }));

    await waitFor(() => expect(drafts.some((draft) => draft.entity_type === "document" && draft.entity_id === createdNoteId)).toBe(false));
    const preservedCollectionDraft = drafts.find((draft) => draft.id === previousCollectionDraft.id);
    expect(preservedCollectionDraft).toBeTruthy();
    expect(preservedCollectionDraft?.revision).toBe(3);
    expect(parse(preservedCollectionDraft!.content)).toMatchObject({
      description: "Previously edited description",
      nodes: [{ id: "section-notes", title: "Renamed Notes", children: [] }],
    });
    expect(preservedCollectionDraft?.content).not.toContain(createdNoteId);
    expect(api.discardDraft).toHaveBeenCalledWith(createdDocumentDraft!.id, createdDocumentDraft!.revision);
    expect(api.discardDraft).not.toHaveBeenCalledWith(previousCollectionDraft.id, expect.any(Number));
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining("此前的 Collection 修改会保留"));
    confirmation.mockRestore();
  });
});
