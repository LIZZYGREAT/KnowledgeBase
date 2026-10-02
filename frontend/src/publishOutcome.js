export function toPublishOutcome(result) {
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
