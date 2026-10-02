import type { BatchPublishedDrafts, PublishedDraft, PublishOutcome } from "./api";

export function toPublishOutcome(result: PublishedDraft | BatchPublishedDrafts): PublishOutcome {
  const results = "results" in result ? result.results : [result];
  const warnings = [
    ...results.flatMap((item) => item.warnings),
    ...("warnings" in result ? result.warnings : []),
  ];
  return {
    commitRevision: result.commit_revision,
    warnings: [...new Set(warnings)],
    results,
  };
}
