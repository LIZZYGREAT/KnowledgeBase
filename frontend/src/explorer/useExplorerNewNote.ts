import { useState } from "react";
import { createBlankDocument, discardDraft, type Draft } from "../api";
import { addEntityReference, removeCollectionNode } from "../collectionEditing";
import { findEntityNodeId } from "./explorerModel";
import { makeDocumentId, newNoteWorkspacePath } from "../newNoteFlow";
import type { CollectionDraftController } from "../useCollectionDraft";
import type { Navigate } from "./ExplorerTypes";

interface UseExplorerNewNoteOptions {
  collectionDraft: CollectionDraftController;
  selectedCollectionId: string;
  navigate: Navigate;
}

export function useExplorerNewNote({
  collectionDraft,
  selectedCollectionId,
  navigate,
}: UseExplorerNewNoteOptions) {
  const [newNoteTarget, setNewNoteTarget] = useState<{ sectionId: string; title: string } | null>(null);
  const [newNoteError, setNewNoteError] = useState("");
  const [newNoteBusy, setNewNoteBusy] = useState(false);
  const [createdNoteDraft, setCreatedNoteDraft] = useState<Draft | null>(null);

  function startNewNoteHere(sectionId: string, sectionTitle: string) {
    setNewNoteTarget({ sectionId, title: sectionTitle });
    setNewNoteError("");
    setCreatedNoteDraft(null);
  }

  async function createNoteHere(
    title: string,
    documentType: "paper-note" | "learning-note" | "course-note",
  ) {
    if (!newNoteTarget || !collectionDraft.collection || collectionDraft.collection.status !== "active") return;
    setNewNoteBusy(true);
    setNewNoteError("");
    let created = createdNoteDraft;
    try {
      if (!created) {
        await collectionDraft.flush();
        const entityId = makeDocumentId(title, globalThis.crypto.randomUUID());
        created = await createBlankDocument(title, documentType, entityId);
        setCreatedNoteDraft(created);
        collectionDraft.change((current) => addEntityReference(
          current,
          "document",
          created!.entity_id,
          title,
          newNoteTarget.sectionId,
        ));
      }
      await enterNewNoteWorkspace(created);
    } catch (reason) {
      setNewNoteError(errorMessage(reason));
    } finally {
      setNewNoteBusy(false);
    }
  }

  async function enterNewNoteWorkspace(draft: Draft) {
    if (!newNoteTarget || !selectedCollectionId) return;
    const savedCollectionDraft = await collectionDraft.flush();
    if (!savedCollectionDraft) throw new Error("Collection Draft 尚未保存；请重试。 ");
    setNewNoteTarget(null);
    setCreatedNoteDraft(null);
    navigate(newNoteWorkspacePath(draft.entity_id, selectedCollectionId));
  }

  async function continueNewNoteWorkspace() {
    if (!createdNoteDraft) return;
    try {
      await enterNewNoteWorkspace(createdNoteDraft);
    } catch (reason) {
      setNewNoteError(errorMessage(reason));
    }
  }

  async function cancelNewNoteHere() {
    if (newNoteBusy) return;
    try {
      if (createdNoteDraft && newNoteTarget) {
        collectionDraft.change((current) => {
          const nodeId = findEntityNodeId(current.nodes, "document", createdNoteDraft.entity_id);
          return nodeId ? removeCollectionNode(current, nodeId) : current;
        });
        await collectionDraft.flush();
        await discardDraft(createdNoteDraft.id, createdNoteDraft.revision);
      }
      setNewNoteTarget(null);
      setCreatedNoteDraft(null);
      setNewNoteError("");
    } catch (reason) {
      setNewNoteError(errorMessage(reason));
    }
  }

  return {
    newNoteTarget,
    newNoteError,
    newNoteBusy,
    createdNoteDraft,
    startNewNoteHere,
    createNoteHere,
    enterNewNoteWorkspace,
    continueNewNoteWorkspace,
    cancelNewNoteHere,
  };
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
