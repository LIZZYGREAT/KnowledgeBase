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

function formatSelectedLines(value, start, end, action) {
  const previousLineBreak = start === 0 ? -1 : value.lastIndexOf("\n", start - 1);
  const rangeStart = previousLineBreak + 1;
  const nextLineBreak = value.indexOf("\n", end);
  const rangeEnd = nextLineBreak < 0 ? value.length : nextLineBreak;
  const segment = value.slice(rangeStart, rangeEnd);
  const pieces = segment.split(/(\r\n|\r|\n)/);
  const lines = [];
  let oldCursor = rangeStart;
  let newCursor = rangeStart;
  let formatted = "";

  for (let index = 0; index < pieces.length; index += 2) {
    const originalLine = pieces[index] ?? "";
    const separator = pieces[index + 1] ?? "";
    const indentation = /^[\t ]*/.exec(originalLine)?.[0] ?? "";
    const body = originalLine.slice(indentation.length);
    let oldPrefixLength = indentation.length;
    let newPrefix = indentation;
    let lineBody = body;

    if (action === "heading") {
      const headingPrefix = /^(#{1,6}[\t ]+)/.exec(body)?.[0] ?? "";
      oldPrefixLength += headingPrefix.length;
      lineBody = body.slice(headingPrefix.length);
      newPrefix = `${indentation}## `;
    } else if (action === "blockquote") {
      const quotePrefix = /^(>[\t ]?)/.exec(body)?.[0] ?? "";
      if (quotePrefix) {
        oldPrefixLength += quotePrefix.length;
        lineBody = body.slice(quotePrefix.length);
      } else {
        newPrefix = `${indentation}> `;
      }
    } else {
      const listPrefix = /^(?:[-+*]|\d+[.)])[\t ]+/.exec(body)?.[0] ?? "";
      const ordered = /^\d+[.)]/.test(listPrefix);
      const bullet = /^[-+*]/.test(listPrefix);
      if (listPrefix) {
        oldPrefixLength += listPrefix.length;
        lineBody = body.slice(listPrefix.length);
      }
      if (action === "bulletList") {
        newPrefix = `${indentation}${bullet ? "" : "- "}`;
      } else {
        newPrefix = `${indentation}${ordered ? "" : `${index / 2 + 1}. `}`;
      }
    }

    const transformedLine = `${newPrefix}${lineBody}`;
    lines.push({
      oldStart: oldCursor,
      oldEnd: oldCursor + originalLine.length,
      oldPrefixLength,
      oldBodyLength: Math.max(0, originalLine.length - oldPrefixLength),
      newStart: newCursor,
      newPrefixLength: newPrefix.length,
      transformedLine,
    });
    formatted += transformedLine + separator;
    oldCursor += originalLine.length + separator.length;
    newCursor += transformedLine.length + separator.length;
  }

  function mapOffset(offset, bias) {
    const line = lines.find((item) => offset <= item.oldEnd) ?? lines.at(-1);
    if (!line) return offset;
    const oldBodyStart = line.oldStart + line.oldPrefixLength;
    if (offset < oldBodyStart || (offset === oldBodyStart && bias === "start")) {
      return line.newStart + line.newPrefixLength;
    }
    const bodyOffset = Math.max(0, Math.min(offset - oldBodyStart, line.oldBodyLength));
    return line.newStart + line.newPrefixLength + bodyOffset;
  }

  const mappedStart = mapOffset(start, "start");
  const mappedEnd = start === end ? mappedStart : mapOffset(end, "end");
  return {
    value: `${value.slice(0, rangeStart)}${formatted}${value.slice(rangeEnd)}`,
    selectionStart: mappedStart,
    selectionEnd: mappedEnd,
  };
}

export function applyMarkdownFormatting(value, start, end, action) {
  const from = Math.max(0, Math.min(start, value.length));
  const to = Math.max(from, Math.min(end, value.length));
  const selected = value.slice(from, to);
  const before = value.slice(0, from);
  const after = value.slice(to);

  if (action === "link") {
    if (!selected) {
      return {
        value: `${before}[text](https://)${after}`,
        selectionStart: from + 1,
        selectionEnd: from + 5,
      };
    }
    const prefix = `[${selected}](`;
    const url = "https://";
    return {
      value: `${before}${prefix}${url})${after}`,
      selectionStart: from + prefix.length,
      selectionEnd: from + prefix.length + url.length,
    };
  }

  if (["heading", "blockquote", "bulletList", "numberedList"].includes(action)) {
    return formatSelectedLines(value, from, to, action);
  }

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
