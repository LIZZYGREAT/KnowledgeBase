import type { DraftComparison, DraftEntityType, DraftPreflight } from "./api";

export interface PublishReviewItem {
  label: string;
  entityType: DraftEntityType;
  draftRevision: number;
  preflight: DraftPreflight;
  comparison: DraftComparison;
}

export interface PublishChangeSummary {
  changedBlockCount: number;
  metadataByTarget: Array<{ label: string; fields: string[] }>;
  collectionChangesByTarget: Array<{ label: string; fields: string[] }>;
  collectionUpdated: boolean;
}

export interface DiffLine {
  kind: "context" | "added" | "removed";
  text: string;
}

export function countChangedMarkdownBlocks(before: string, after: string, type?: DraftEntityType): number;
export function summarizePublishChanges(items: PublishReviewItem[]): PublishChangeSummary;
export function createLineDiff(before: string, after: string): DiffLine[];
