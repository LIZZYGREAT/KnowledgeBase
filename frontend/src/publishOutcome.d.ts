import type { BatchPublishedDrafts, PublishedDraft, PublishOutcome } from "./api";

export function toPublishOutcome(result: PublishedDraft | BatchPublishedDrafts): PublishOutcome;
