import type { EntityType } from "./api";

export function readFrontmatterField(content: string, type: EntityType, key: string): unknown;
export function patchYamlField(content: string, type: EntityType, key: string, value: unknown): string;
