import assert from "node:assert/strict";
import { createElement } from "react";
import { test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { remarkPresentationAnnotations } from "../../src/markdownAnnotations";
import { remarkMarkdownStyles } from "../../src/markdownStyleSyntax";

function renderMarkdown(content, annotations = []) {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown,
      {
        remarkPlugins: [
          remarkGfm,
          remarkMath,
          [remarkMarkdownStyles, { source: content }],
          [remarkPresentationAnnotations, { annotations }],
        ],
      },
      content,
    ),
  );
}

test("renders empty Markdown without a Presentation Annotation runtime error", () => {
  assert.doesNotThrow(() => renderMarkdown(""));
});

test("renders ordinary Markdown without annotations", () => {
  assert.match(renderMarkdown("# A title\n\nA normal paragraph."), /<h1>A title<\/h1>/);
});

test("renders Markdown with an active Presentation Annotation", () => {
  const content = "A normal paragraph with a selected phrase.";
  const selected = "selected phrase";
  const markup = renderMarkdown(content, [{
    id: "annotation-1",
    entity_type: "document",
    entity_id: "example",
    style_type: "highlight",
    style_value: "yellow",
    selected_text: selected,
    prefix_text: "",
    suffix_text: "",
    start_offset: content.indexOf(selected),
    end_offset: content.indexOf(selected) + selected.length,
    base_content_hash: "0".repeat(64),
    status: "active",
    created_at: "now",
    updated_at: "now",
  }]);

  assert.match(markup, /class="presentation-annotation annotation-highlight-yellow"/);
  assert.match(markup, /data-annotation-ids="annotation-1"/);
  assert.match(markup, /selected phrase/);
});

test("keeps annotation source offsets aligned inside nested Markdown marks", () => {
  const content = "前 ==**selected phrase**== 后";
  const selected = "selected phrase";
  const annotation = {
    id: "annotation-in-mark",
    entity_type: "document",
    entity_id: "example",
    style_type: "highlight",
    style_value: "yellow",
    selected_text: selected,
    prefix_text: "",
    suffix_text: "",
    start_offset: content.indexOf(selected),
    end_offset: content.indexOf(selected) + selected.length,
    base_content_hash: "0".repeat(64),
    status: "active",
    created_at: "now",
    updated_at: "now",
  };
  const adjacentStart = content.indexOf("后");
  const markup = renderMarkdown(content, [annotation, {
    ...annotation,
    id: "annotation-after-mark",
    selected_text: "后",
    start_offset: adjacentStart,
    end_offset: adjacentStart + 1,
  }]);

  assert.match(markup, /<mark><strong><span class="presentation-annotation annotation-highlight-yellow"[^>]*>selected phrase<\/span><\/strong><\/mark>/);
  assert.match(markup, /<\/mark> <span class="presentation-annotation annotation-highlight-yellow"[^>]*>后<\/span>/);
});
