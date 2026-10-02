import { useEffect, useState } from "react";
import {
  getCollection,
  listAllEntities,
  listAllUnfiledDocuments,
  listCollections,
  listUsage,
  type Collection,
  type EntitySummary,
} from "../api";
import { restoreExplorerPreferences } from "../explorerTree.js";
import type { ExplorerView, Resource } from "./ExplorerTypes";

const PREFERENCES_KEY = "knowledgebase.explorer-preferences";

export function useExplorerPreferences() {
  const [preferences] = useState(readPreferences);
  return preferences;
}

export function useExplorerResources(view: ExplorerView, selectedCollectionId: string) {
  const collectionsResource = useResource(
    "collections:active-and-archived",
    () => Promise.all([listCollections("active"), listCollections("archived")]).then(([active, archived]) =>
      [...active, ...archived].sort((left, right) => left.position - right.position || left.title.localeCompare(right.title)),
    ),
  );
  const collectionResource = useResource<Collection | null>(
    `collection:${selectedCollectionId}`,
    () => selectedCollectionId ? getCollection(selectedCollectionId) : Promise.resolve(null),
  );
  const virtualResource = useResource<EntitySummary[]>(`virtual-view:${view}`, async () => {
    if (view === "all") return listAllEntities("document");
    if (view === "unfiled") return listAllUnfiledDocuments();
    if (view === "recent") {
      const recent = await listUsage("recent", 100);
      return recent.map((item) => ({
        id: item.entity_id,
        title: item.title,
        entity_type: "document" as const,
        metadata: {},
      }));
    }
    return [];
  });
  return { collectionsResource, collectionResource, virtualResource };
}

function useResource<T>(key: string, load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    setLoading(true);
    load()
      .then((value) => { if (active) setData(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "未知错误"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, version]);
  return { data, error, loading, retry: () => setVersion((current) => current + 1) };
}

function readPreferences() {
  try {
    return restoreExplorerPreferences(window.localStorage.getItem(PREFERENCES_KEY));
  } catch {
    return restoreExplorerPreferences(null);
  }
}
