const inlinePairs = {
  bold: ["**", "**"],
  italic: ["*", "*"],
  strike: ["~~", "~~"],
  code: ["`", "`"],
  inlineMath: ["$", "$"],
};

function countLineBreaks(value) {
  return (value.match(/\r\n|\r|\n/g) ?? []).length;
}

function ensureBlankLineBefore(value, lineEnding) {
  if (!value) return value;
  const trailingBreaks = value.match(/(?:\r\n|\r|\n)+$/)?.[0] ?? "";
  return value + lineEnding.repeat(Math.max(0, 2 - countLineBreaks(trailingBreaks)));
}

function ensureBlankLineAfter(value, lineEnding) {
  if (!value) return value;
  const leadingBreaks = value.match(/^(?:\r\n|\r|\n)+/)?.[0] ?? "";
  return lineEnding.repeat(Math.max(0, 2 - countLineBreaks(leadingBreaks))) + value;
}

function wrapBlockMath(before, selected, after, open, close, lineEnding) {
  const paddedBefore = ensureBlankLineBefore(before, lineEnding);
  const paddedAfter = ensureBlankLineAfter(after, lineEnding);
  const selectionStart = paddedBefore.length + open.length;
  return {
    value: `${paddedBefore}${open}${selected}${close}${paddedAfter}`,
    selectionStart,
    selectionEnd: selectionStart + selected.length,
  };
}

export function applyMarkdownFormatting(value, start, end, action) {
  const from = Math.max(0, Math.min(start, value.length));
  const to = Math.max(from, Math.min(end, value.length));
  const selected = value.slice(from, to);
  const before = value.slice(0, from);
  const after = value.slice(to);

  if (action in inlinePairs) {
    const [open, close] = inlinePairs[action];
    if (action === "inlineMath" && !selected) {
      return {
        value: `${before}$ $${after}`,
        selectionStart: from + 1,
        selectionEnd: from + 2,
      };
    }
    return {
      value: `${before}${open}${selected}${close}${after}`,
      selectionStart: from + open.length,
      selectionEnd: from + open.length + selected.length,
    };
  }

  if (action === "displayMath") {
    const open = "$$\n";
    const close = "\n$$";
    const lineEnding = value.match(/\r\n|\r|\n/)?.[0] ?? "\n";
    return wrapBlockMath(before, selected, after, open, close, lineEnding);
  }

  if (action === "alignedMath") {
    const open = "$$\n\\begin{aligned}\n";
    const close = "\n\\end{aligned}\n$$";
    const lineEnding = value.match(/\r\n|\r|\n/)?.[0] ?? "\n";
    return wrapBlockMath(before, selected, after, open, close, lineEnding);
  }

  throw new Error(`Unsupported Markdown formatting action: ${action}`);
}
