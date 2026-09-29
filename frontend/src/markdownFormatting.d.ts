export type MarkdownFormattingAction =
  | "bold"
  | "italic"
  | "strike"
  | "code"
  | "inlineMath"
  | "displayMath"
  | "alignedMath";

export interface MarkdownFormattingResult {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

export function applyMarkdownFormatting(
  value: string,
  start: number,
  end: number,
  action: MarkdownFormattingAction,
): MarkdownFormattingResult;
