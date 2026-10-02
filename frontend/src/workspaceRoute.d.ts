import type { EntityType } from "./api";

export function entityWorkspaceUrl(
  type: EntityType,
  id: string,
  options?: { collectionId?: string; edit?: boolean; publishAll?: boolean },
): string;
