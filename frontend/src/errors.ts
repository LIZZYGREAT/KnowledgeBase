export function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "未知错误";
}
