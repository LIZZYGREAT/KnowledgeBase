import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRuntimeDraftSession } from "../../src/draft/useRuntimeDraftSession";
import type { Draft } from "../../src/api";

const api = vi.hoisted(() => ({
  listDrafts: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  discardDraft: vi.fn(),
  getDraft: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

function makeDraft(content: string, revision = 1, entityId = "session-note"): Draft {
  return {
    id: "draft-session",
    entity_type: "document",
    entity_id: entityId,
    base_git_revision: "base-revision",
    base_content_hash: "base-hash",
    content,
    revision,
    created_at: "2026-10-03T00:00:00Z",
    updated_at: "2026-10-03T00:00:00Z",
  };
}

function sessionOptions(entityId = "session-note") {
  return {
    entityType: "document" as const,
    entityId,
    enabled: true,
    initialContent: `Canonical ${entityId}`,
    initialContentReady: true,
  };
}

describe("Runtime Draft session", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listDrafts.mockResolvedValue([]);
    api.createDraft.mockImplementation(async (_type: string, entityId: string, content: string) => ({
      draft: makeDraft(content, 1, entityId),
      created: true,
    }));
    api.updateDraft.mockImplementation(async (draftId: string, content: string, expectedRevision: number) =>
      makeDraft(content, expectedRevision + 1));
    api.getDraft.mockImplementation(async (draftId: string) => makeDraft("Latest saved content", 2));
    api.discardDraft.mockResolvedValue({ deleted: true });
  });

  it("seeds a clean session from Canonical and acquires a Draft on demand", async () => {
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("clean"));
    expect(result.current.content).toBe("Canonical session-note");

    let acquired: Draft | undefined;
    await act(async () => {
      acquired = await result.current.acquireDraft();
    });

    expect(api.createDraft).toHaveBeenCalledWith("document", "session-note", "Canonical session-note");
    expect(acquired?.content).toBe("Canonical session-note");
    expect(result.current.state).toBe("saved");
  });

  it("does not start a background save when an unsaved session unmounts", async () => {
    const { result, unmount } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("clean"));

    act(() => result.current.updateContent("Unsaved before unmount"));
    unmount();

    expect(api.createDraft).not.toHaveBeenCalled();
    expect(api.updateDraft).not.toHaveBeenCalled();
  });

  it("arms the browser beforeunload warning only while the session is dirty", async () => {
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("clean"));

    const cleanEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    act(() => result.current.updateContent("Unsaved browser-close content"));
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    await act(async () => { await result.current.saveNow(); });
    const savedEvent = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedEvent);
    expect(savedEvent.defaultPrevented).toBe(false);
  });

  it("queues concurrent edits behind the in-flight revision update", async () => {
    const first = makeDraft("Initial saved content");
    let resolveFirst!: (draft: Draft) => void;
    api.listDrafts.mockResolvedValue([first]);
    api.updateDraft
      .mockImplementationOnce(() => new Promise<Draft>((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(makeDraft("Second edit", 3));
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("saved"));

    let firstSave!: Promise<Draft | null>;
    let queuedSave!: Promise<Draft | null>;
    await act(async () => {
      result.current.updateContent("First edit");
      firstSave = result.current.saveNow();
      result.current.updateContent("Second edit");
      queuedSave = result.current.saveNow();
      await Promise.resolve();
      resolveFirst(makeDraft("First edit", 2));
      await Promise.all([firstSave, queuedSave]);
    });

    expect(api.updateDraft).toHaveBeenNthCalledWith(1, first.id, "First edit", 1);
    expect(api.updateDraft).toHaveBeenNthCalledWith(2, first.id, "Second edit", 2);
    expect(result.current.content).toBe("Second edit");
    expect(result.current.state).toBe("saved");
  });

  it("rejects Discard while a Draft save is in flight", async () => {
    const existing = makeDraft("Saved content");
    let resolveUpdate!: (draft: Draft) => void;
    api.listDrafts.mockResolvedValue([existing]);
    api.updateDraft.mockImplementationOnce(() => new Promise<Draft>((resolve) => {
      resolveUpdate = resolve;
    }));
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("saved"));

    let pendingSave!: Promise<Draft | null>;
    act(() => {
      result.current.updateContent("Saving now");
      pendingSave = result.current.saveNow();
    });
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledOnce());

    await expect(result.current.discard()).rejects.toThrow("请等待保存完成");
    expect(api.discardDraft).not.toHaveBeenCalled();

    await act(async () => {
      resolveUpdate(makeDraft("Saving now", 2));
      await pendingSave;
    });
  });

  it("rejects Discard during a Runtime Draft conflict", async () => {
    const existing = makeDraft("Saved content");
    api.listDrafts.mockResolvedValue([existing]);
    api.updateDraft.mockRejectedValueOnce(Object.assign(new Error("revision changed"), {
      status: 409,
      code: "draft_revision_conflict",
    }));
    api.getDraft.mockResolvedValue(makeDraft("Other session content", 2));
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("saved"));

    await act(async () => {
      result.current.updateContent("Local content");
      await expect(result.current.saveNow()).rejects.toThrow("revision changed");
    });
    expect(result.current.state).toBe("runtime-conflict");

    await expect(result.current.discard()).rejects.toThrow("请先处理 Runtime Draft 冲突");
    expect(api.discardDraft).not.toHaveBeenCalled();
  });

  it("allows Discard after a Draft is saved", async () => {
    const saved = makeDraft("Saved content");
    api.listDrafts.mockResolvedValue([saved]);
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("saved"));

    await act(async () => { await result.current.discard(); });

    expect(api.discardDraft).toHaveBeenCalledWith(saved.id, saved.revision);
    expect(result.current.state).toBe("clean");
  });

  it("cannot delete another session Draft when creation collides in flight", async () => {
    const remoteDraft = makeDraft("Other session content");
    let resolveCreate!: (result: { draft: Draft; created: boolean }) => void;
    api.createDraft.mockImplementationOnce(() => new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("clean"));

    let pendingSave!: Promise<Draft | null>;
    act(() => {
      result.current.updateContent("Local content");
      pendingSave = result.current.saveNow();
    });
    await waitFor(() => expect(api.createDraft).toHaveBeenCalledOnce());

    await expect(result.current.discard()).rejects.toThrow("请等待保存完成");
    expect(api.discardDraft).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ draft: remoteDraft, created: false });
      await expect(pendingSave).rejects.toThrow("另一个会话已为此内容创建了不同的 Draft");
    });
    expect(result.current.state).toBe("runtime-conflict");
    expect(api.discardDraft).not.toHaveBeenCalledWith(remoteDraft.id, remoteDraft.revision);
  });

  it("keeps local content through revision conflict and applies a merge against the latest revision", async () => {
    const existing = makeDraft("First saved version");
    const latest = makeDraft("Other session version", 2);
    api.listDrafts.mockResolvedValue([existing]);
    api.updateDraft
      .mockRejectedValueOnce(Object.assign(new Error("revision changed"), {
        status: 409,
        code: "draft_revision_conflict",
      }))
      .mockRejectedValueOnce(Object.assign(new Error("revision changed again"), {
        status: 409,
        code: "draft_revision_conflict",
      }))
      .mockResolvedValueOnce(makeDraft("Merged local and remote", 4));
    api.getDraft
      .mockResolvedValueOnce(latest)
      .mockResolvedValueOnce(makeDraft("Third session version", 3));
    const { result } = renderHook(() => useRuntimeDraftSession(sessionOptions()));
    await waitFor(() => expect(result.current.state).toBe("saved"));

    await act(async () => {
      result.current.updateContent("Local unsaved version");
      await expect(result.current.saveNow()).rejects.toThrow("revision changed");
    });

    expect(result.current.state).toBe("runtime-conflict");
    expect(result.current.runtimeConflict?.localContent).toBe("Local unsaved version");
    expect(result.current.runtimeConflict?.existingDraft.revision).toBe(2);
    expect(result.current.content).toBe("Local unsaved version");

    await act(async () => {
      await expect(result.current.updateLatestDraft("Merged candidate")).rejects.toThrow("revision changed again");
    });
    expect(result.current.state).toBe("runtime-conflict");
    expect(result.current.runtimeConflict?.localContent).toBe("Merged candidate");
    expect(result.current.runtimeConflict?.existingDraft.revision).toBe(3);

    let updated: Draft | undefined;
    await act(async () => {
      updated = await result.current.updateLatestDraft("Merged local and remote");
    });

    expect(api.updateDraft).toHaveBeenLastCalledWith(existing.id, "Merged local and remote", 3);
    expect(updated?.revision).toBe(4);
    expect(result.current.state).toBe("saved");
    expect(result.current.content).toBe("Merged local and remote");
    expect(result.current.runtimeConflict).toBeNull();
  });

  it("ignores Draft loads from an Entity session that has already been replaced", async () => {
    let resolveFirst!: (drafts: Draft[]) => void;
    let resolveSecond!: (drafts: Draft[]) => void;
    api.listDrafts
      .mockImplementationOnce(() => new Promise<Draft[]>((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<Draft[]>((resolve) => { resolveSecond = resolve; }));
    const { result, rerender } = renderHook(
      ({ entityId }: { entityId: string }) => useRuntimeDraftSession(sessionOptions(entityId)),
      { initialProps: { entityId: "first-note" } },
    );
    await waitFor(() => expect(api.listDrafts).toHaveBeenCalledTimes(1));
    rerender({ entityId: "second-note" });
    await waitFor(() => expect(api.listDrafts).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveFirst([makeDraft("Stale first-note draft", 1, "first-note")]);
      resolveSecond([]);
    });
    await waitFor(() => expect(result.current.state).toBe("clean"));

    expect(result.current.content).toBe("Canonical second-note");
    expect(result.current.draft).toBeNull();
  });

  it("ignores a save response from a session that has already been replaced", async () => {
    let resolveFirst!: (result: { draft: Draft; created: boolean }) => void;
    api.createDraft.mockImplementationOnce((_type: string, entityId: string, content: string) =>
      new Promise((resolve) => { resolveFirst = resolve; }));
    const { result, rerender } = renderHook(
      ({ entityId }: { entityId: string }) => useRuntimeDraftSession(sessionOptions(entityId)),
      { initialProps: { entityId: "first-note" } },
    );
    await waitFor(() => expect(result.current.state).toBe("clean"));

    let pendingSave!: Promise<Draft | null>;
    await act(async () => {
      result.current.updateContent("First session edit");
      pendingSave = result.current.saveNow();
      await Promise.resolve();
    });
    expect(api.createDraft).toHaveBeenCalledOnce();

    rerender({ entityId: "second-note" });
    await waitFor(() => expect(result.current.state).toBe("clean"));
    await act(async () => {
      resolveFirst({
        draft: makeDraft("First session edit", 1, "first-note"),
        created: true,
      });
      await pendingSave;
    });

    expect(result.current.content).toBe("Canonical second-note");
    expect(result.current.draft).toBeNull();
    expect(result.current.state).toBe("clean");
  });
});
