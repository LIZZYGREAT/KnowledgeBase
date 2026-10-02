import { useEffect, useState } from "react";
import { parse as parseYaml } from "yaml";
import {
  createDraft,
  discardDraft,
  getCollection,
  listDrafts,
  publishDraftsBatch,
  updateDraft,
  type Collection,
  type CollectionSummary,
  type Draft,
  type PublishOutcome,
} from "../api";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft } from "../collectionDraftModel";
import { changedCollectionPositions, moveCollectionInOrder } from "../collectionOrdering";
import { toPublishOutcome } from "../publishOutcome";
import type { CollectionDraftController } from "../useCollectionDraft";
import type { Resource } from "./ExplorerTypes";

interface UseExplorerCollectionOrderingOptions {
  collectionSummaries: CollectionSummary[];
  collectionsResource: Resource<CollectionSummary[]>;
  selectedCollectionId: string;
  collectionDraft: CollectionDraftController;
}

export function useExplorerCollectionOrdering({
  collectionSummaries,
  collectionsResource,
  selectedCollectionId,
  collectionDraft,
}: UseExplorerCollectionOrderingOptions) {
  const [organizationOrderDrafts, setOrganizationOrderDrafts] = useState<Draft[]>([]);
  const [organizationDraftsLoading, setOrganizationDraftsLoading] = useState(true);
  const [orderingError, setOrderingError] = useState("");
  const [orderingNotice, setOrderingNotice] = useState("");
  const [orderingBusy, setOrderingBusy] = useState(false);
  const [publishOutcome, setPublishOutcome] = useState<PublishOutcome | null>(null);

  useEffect(() => { if (orderingNotice) setPublishOutcome(null); }, [orderingNotice]);

  useEffect(() => {
    setOrderingError("");
    setOrderingNotice("");
    setPublishOutcome(null);
  }, [selectedCollectionId]);

  useEffect(() => {
    let active = true;
    const summaries = collectionsResource.data;
    setOrganizationDraftsLoading(true);
    if (!summaries) {
      setOrganizationOrderDrafts([]);
      setOrganizationDraftsLoading(false);
      return () => { active = false; };
    }
    void readCollectionOrderEntries(summaries)
      .then((entries) => {
        if (!active) return;
        setOrganizationOrderDrafts(entries
          .filter((entry) => entry.draft && entry.position !== entry.summary.position)
          .map((entry) => entry.draft!));
      })
      .catch((reason: unknown) => {
        if (active) setOrderingError(errorMessage(reason));
      })
      .finally(() => { if (active) setOrganizationDraftsLoading(false); });
    return () => { active = false; };
  }, [collectionsResource.data]);

  async function moveSelectedCollection(direction: "up" | "down") {
    setOrderingBusy(true);
    setOrderingError("");
    setOrderingNotice("");
    try {
      if (collectionDraft.status === "unsaved" || collectionDraft.status === "saving") {
        await collectionDraft.flush();
      }
      if (["loading", "error", "runtime-conflict", "canonical-conflict"].includes(collectionDraft.status)) {
        throw new Error("请先载入并处理当前 Collection Draft，再调整排序。");
      }
      const entries = await readCollectionOrderEntries(collectionSummaries, true);
      const currentOrder = entries
        .map((entry) => ({ ...entry.summary, position: entry.position }))
        .sort((left, right) => left.position - right.position || left.title.localeCompare(right.title));
      const reordered = moveCollectionInOrder(currentOrder, selectedCollectionId, direction);
      const positionChanges = changedCollectionPositions(currentOrder, reordered);
      if (!positionChanges.length) return;
      const entriesById = new Map(entries.map((entry) => [entry.summary.id, entry]));
      for (const item of positionChanges) {
        const entry = entriesById.get(item.id)!;
        const canonical = entry.canonical ?? await getCollection(item.id);
        if (item.position === canonical.position) {
          if (entry.draft) await discardDraft(entry.draft.id, entry.draft.revision);
          continue;
        }
        const current = entry.draft
          ? parseCollectionDraft(entry.draft.content, canonical)
          : collectionToDraft(canonical);
        const draftContent = serializeCollectionDraft({ ...current, position: item.position });
        if (entry.draft) {
          if (entry.draft.content !== draftContent) {
            await updateDraft(entry.draft.id, draftContent, entry.draft.revision);
          }
          continue;
        }
        const acquisition = await createDraft("collection", item.id, draftContent);
        if (acquisition.created || acquisition.draft.content === draftContent) continue;
        if (!isPositionOnlyDraft(acquisition.draft, canonical)) {
          throw new Error(`Collection ${item.title} 在另一标签页中已有其他 Draft；请先检查并处理。`);
        }
        const acquiredCollection = parseCollectionDraft(acquisition.draft.content, canonical);
        if (acquiredCollection.position !== item.position) {
          await updateDraft(acquisition.draft.id, draftContent, acquisition.draft.revision);
        }
      }
      const refreshedEntries = await readCollectionOrderEntries(collectionSummaries, true);
      setOrganizationOrderDrafts(refreshedEntries
        .filter((entry) => entry.draft && entry.position !== entry.summary.position)
        .map((entry) => entry.draft!));
      setOrderingNotice(refreshedEntries.some((entry) => entry.draft && entry.position !== entry.summary.position)
        ? "排序 Draft 已保存；可以继续调整，再统一发布。"
        : "排序已恢复为当前正式顺序。");
    } catch (reason) {
      setOrderingError(errorMessage(reason));
      try {
        const refreshedEntries = await readCollectionOrderEntries(collectionSummaries);
        setOrganizationOrderDrafts(refreshedEntries
          .filter((entry) => entry.draft && entry.position !== entry.summary.position)
          .map((entry) => entry.draft!));
      } catch {
        // Keep the operation error visible; the next resource refresh can recover pending state.
      }
    } finally {
      setOrderingBusy(false);
    }
  }

  async function publishOrganizationChanges() {
    setOrderingBusy(true);
    setOrderingError("");
    setOrderingNotice("");
    try {
      const entries = await readCollectionOrderEntries(collectionSummaries, true);
      const pending = entries.filter((entry) => entry.draft && entry.position !== entry.summary.position);
      if (!pending.length) {
        setOrganizationOrderDrafts([]);
        setOrderingNotice("没有未发布的 Collection 排序修改。");
        return;
      }
      const result = await publishDraftsBatch(pending.map((entry) => ({
        draft_id: entry.draft!.id,
        expected_revision: entry.draft!.revision,
      })));
      const selectedWasReordered = pending.some((entry) => entry.summary.id === selectedCollectionId);
      if (selectedWasReordered) collectionDraft.reset(await getCollection(selectedCollectionId));
      setOrganizationOrderDrafts([]);
      collectionsResource.retry();
      setPublishOutcome(toPublishOutcome(result));
    } catch (reason) {
      setOrderingError((reason as { status?: number })?.status === 409
        ? "Collection 排序 Draft 在发布前发生变化；请重新载入并检查。"
        : errorMessage(reason));
      if ((reason as { status?: number })?.status === 409) collectionsResource.retry();
    } finally {
      setOrderingBusy(false);
    }
  }

  return {
    organizationOrderDrafts,
    organizationDraftsLoading,
    orderingError,
    orderingNotice,
    orderingBusy,
    publishOutcome,
    moveSelectedCollection,
    publishOrganizationChanges,
  };
}

export function readDraftPosition(draft: Draft): number {
  try {
    const value: unknown = parseYaml(draft.content);
    if (!isYamlRecord(value) || !Number.isInteger(value.position)) return 0;
    return value.position as number;
  } catch {
    return 0;
  }
}

interface CollectionOrderEntry {
  summary: CollectionSummary;
  canonical: Collection | null;
  draft: Draft | null;
  position: number;
}

async function readCollectionOrderEntries(
  summaries: CollectionSummary[],
  rejectUnrelatedDrafts = false,
): Promise<CollectionOrderEntry[]> {
  return Promise.all(summaries.map(async (summary) => {
    const drafts = await listDrafts("collection", summary.id);
    if (!drafts.length) return { summary, canonical: null, draft: null, position: summary.position };
    if (drafts.length !== 1) {
      if (rejectUnrelatedDrafts) {
        throw new Error(`Collection ${summary.title} 有多个活动 Draft；请先检查并处理。`);
      }
      return { summary, canonical: null, draft: null, position: summary.position };
    }

    const canonical = await getCollection(summary.id);
    const draft = drafts[0];
    if (!isPositionOnlyDraft(draft, canonical)) {
      if (rejectUnrelatedDrafts) {
        throw new Error(`请先发布或丢弃 Collection ${summary.title} 的其他 Draft，再调整排序。`);
      }
      return { summary, canonical: null, draft: null, position: summary.position };
    }
    const position = parseCollectionDraft(draft.content, canonical).position;
    return { summary, canonical, draft, position };
  }));
}

function isPositionOnlyDraft(draft: Draft, canonical: Collection) {
  try {
    const draftValue: unknown = parseYaml(draft.content);
    const canonicalValue: unknown = parseYaml(serializeCollectionDraft(collectionToDraft(canonical)));
    if (!isYamlRecord(draftValue) || !isYamlRecord(canonicalValue)) return false;
    const draftContent = { ...draftValue };
    const canonicalContent = { ...canonicalValue };
    delete draftContent.position;
    delete canonicalContent.position;
    return stableYamlValue(draftContent) === stableYamlValue(canonicalContent);
  } catch {
    return false;
  }
}

function isYamlRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stableYamlValue(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableYamlValue).join(",")}]`;
  if (value && typeof value === "object") {
    const fields = Object.entries(value).sort(([left], [right]) => left.localeCompare(right));
    return `{${fields.map(([key, item]) => `${JSON.stringify(key)}:${stableYamlValue(item)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
