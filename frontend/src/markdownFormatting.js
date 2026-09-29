const inlinePairs = {
  bold: ["**", "**"],
  italic: ["*", "*"],
  strike: ["~~", "~~"],
  code: ["`", "`"],
  inlineMath: ["$", "$"],
};

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
    return {
      value: `${before}${open}${selected}${close}${after}`,
      selectionStart: from + open.length,
      selectionEnd: from + open.length + selected.length,
    };
  }

  if (action === "alignedMath") {
    const open = "$$\n\\begin{aligned}\n";
    const close = "\n\\end{aligned}\n$$";
    return {
      value: `${before}${open}${selected}${close}${after}`,
      selectionStart: from + open.length,
      selectionEnd: from + open.length + selected.length,
    };
  }

  throw new Error(`Unsupported Markdown formatting action: ${action}`);
}
