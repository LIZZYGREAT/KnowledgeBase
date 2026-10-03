import type { DragEvent } from "react";
import type { EntityType } from "../api";
import type { RegisterBeforeNavigate } from "../navigation";

export type ExplorerView = "collection" | "all" | "unfiled" | "recent";

export interface Resource<T> {
  data: T | null;
  error: string;
  loading: boolean;
  retry: () => void;
}

export type Navigate = (path: string) => void;
export type OpenEntity = (type: EntityType, id: string, clickedFromSearch?: boolean, collectionId?: string) => void;
export type DragPayload =
  | { kind: "reference"; entityType: EntityType; entityId: string; title: string }
  | { kind: "node"; collectionId: string; nodeId: string; entityType?: EntityType; entityId?: string; title?: string };

export interface ExplorerPageProps {
  onOpen: OpenEntity;
  navigate: Navigate;
  registerBeforeNavigate?: RegisterBeforeNavigate;
  embedded?: boolean;
  selectedEntity?: { type: EntityType; id: string };
}

export type ExplorerNodeDragEvent = DragEvent<HTMLElement>;
