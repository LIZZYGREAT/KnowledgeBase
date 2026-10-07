import { useEffect, useState } from "react";
import { errorMessage } from "../errors";
import type { EntitySummary, EntityType, UsageDocument } from "../api";
import { Chip, EmptyState, EntityRow, formatDate, titleCase } from "../ui";
export type Navigate = (path: string) => void;
export type SelectEntity = (type: EntityType, id: string, clickedFromSearch?: boolean) => void;

export interface Resource<T> {
  data: T | null;
  error: string;
  loading: boolean;
  retry: () => void;
}

export function useResource<T>(key: string, load: () => Promise<T>): Resource<T> {
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
      .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, version]);
  return { data, error, loading, retry: () => setVersion((current) => current + 1) };
}

export function readList(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function reviewStatus(entity: EntitySummary) {
  const metadata = entity.metadata;
  if (entity.entity_type === "source") {
    const review = metadata.metadata_review as Record<string, unknown> | undefined;
    return readString(review?.status) || "unreviewed";
  }
  const review = metadata.review as Record<string, unknown> | undefined;
  const human = review?.human as Record<string, unknown> | undefined;
  return readString(human?.status) || "unreviewed";
}

export function maintenanceStatus(entity: EntitySummary) {
  const maintenance = entity.metadata.maintenance as Record<string, unknown> | undefined;
  return readString(maintenance?.status) || "current";
}

export function maintenanceActionCount(
  entities: EntitySummary[],
  proposalCount: number,
  linkIssueCount: number,
  staleAnnotationCount: number,
) {
  const entitiesWithActions = entities.filter((entity) =>
    reviewStatus(entity) === "unreviewed" || maintenanceStatus(entity) === "needs_revision",
  );
  const uniqueEntityCount = new Set(entitiesWithActions.map((entity) => `${entity.entity_type}:${entity.id}`)).size;
  return uniqueEntityCount + proposalCount + linkIssueCount + staleAnnotationCount;
}

export function statusTone(value: string) {
  if (["approved", "verified", "current", "merged"].includes(value)) return "green";
  if (["needs_revision", "needs_attention", "stale", "ambiguous"].includes(value)) return "amber";
  if (["rejected", "failed", "unresolved"].includes(value)) return "rose";
  return "neutral";
}

export function entityPath(entity: Pick<EntitySummary, "entity_type" | "id">) {
  return `/${entity.entity_type === "document" ? "documents" : entity.entity_type === "term" ? "terms" : "sources"}/${encodeURIComponent(entity.id)}`;
}

export function typeLabel(entity: Pick<EntitySummary, "entity_type" | "metadata">) {
  const kind = readString(entity.metadata.type) || entity.entity_type;
  return titleCase(kind);
}

export function EntityList({
  entities,
  onOpen,
  emptyTitle = "这里还没有内容",
  emptyDescription = "正式发布的知识会出现在这里。",
}: {
  entities: EntitySummary[];
  onOpen: (entity: EntitySummary) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (!entities.length) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return (
    <div className="entity-list">
      {entities.map((entity) => (
        <EntityRow
          key={`${entity.entity_type}:${entity.id}`}
          title={entity.title}
          detail={`${typeLabel(entity)} · ${entity.id}`}
          badge={<Chip tone={statusTone(reviewStatus(entity))}>{titleCase(reviewStatus(entity))}</Chip>}
          onClick={() => onOpen(entity)}
        />
      ))}
    </div>
  );
}

export function ViewList({
  entries,
  onOpen,
}: {
  entries: UsageDocument[];
  onOpen: (id: string) => void;
}) {
  if (!entries.length) return <p className="subtle-copy">打开一篇笔记后，它会出现在这里。</p>;
  return (
    <div className="entity-list compact-list">
      {entries.map((entry) => (
        <EntityRow
          key={entry.entity_id}
          title={entry.title}
          detail={`${entry.view_count} 次阅读 · ${formatDate(entry.last_viewed_at)}`}
          onClick={() => onOpen(entry.entity_id)}
        />
      ))}
    </div>
  );
}
