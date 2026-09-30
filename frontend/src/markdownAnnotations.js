function transformPresentationAnnotations(node, annotations) {
  if (!node?.children) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text" && child.value) {
      return annotateTextNode(child, annotations);
    }
    transformPresentationAnnotations(child, annotations);
    return [child];
  });
}

function annotateTextNode(node, annotations) {
  const sourceStart = node.position?.start?.offset;
  if (sourceStart === undefined || !node.value) return [node];
  const matches = annotations.flatMap((annotation) => {
    if (annotation.status !== "active" || !annotation.selected_text) return [];
    const localStart = annotation.start_offset - sourceStart;
    if (localStart < 0 || node.value.slice(localStart, localStart + annotation.selected_text.length) !== annotation.selected_text) return [];
    return [{ start: localStart, end: localStart + annotation.selected_text.length, annotation }];
  });
  if (!matches.length) return [node];

  const boundaries = [...new Set([0, node.value.length, ...matches.flatMap((match) => [match.start, match.end])])]
    .sort((left, right) => left - right);
  const segments = [];
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index];
    const end = boundaries[index + 1];
    if (start === end) continue;
    const value = node.value.slice(start, end);
    const styles = matches
      .filter((match) => match.start <= start && match.end >= end)
      .map((match) => match.annotation);
    if (!styles.length) {
      segments.push({ type: "text", value, position: node.position });
      continue;
    }
    const classes = styles.map((annotation) => {
      const valueClass = annotation.style_value ?? "none";
      return `annotation-${annotation.style_type}-${valueClass}`;
    });
    segments.push({
      type: "presentationAnnotation",
      children: [{ type: "text", value }],
      data: {
        hName: "span",
        hProperties: {
          className: ["presentation-annotation", ...classes].join(" "),
          "data-annotation-ids": styles.map((annotation) => annotation.id).join(" "),
        },
      },
      position: node.position,
    });
  }
  return segments;
}

export function remarkPresentationAnnotations(options = {}) {
  const annotations = options?.annotations ?? [];
  return (tree) => transformPresentationAnnotations(tree, annotations);
}
