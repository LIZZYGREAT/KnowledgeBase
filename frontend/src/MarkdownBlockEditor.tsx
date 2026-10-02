import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { applyMarkdownFormatting, type MarkdownFormattingAction } from "./markdownFormatting";
import {
  parseMarkdownBlocks,
  replaceMarkdownBlock,
  splitMarkdownFrontmatter,
} from "./markdownBlocks";
import { SectionHeading } from "./ui";

const MarkdownContent = lazy(() => import("./Markdown").then((module) => ({ default: module.MarkdownContent })));

const formattingActions: { action: MarkdownFormattingAction; label: string; title: string; text: string }[] = [
  { action: "bold", label: "加粗", title: "加粗", text: "B" },
  { action: "italic", label: "斜体", title: "斜体", text: "I" },
  { action: "strike", label: "删除线", title: "删除线", text: "S" },
  { action: "code", label: "行内代码", title: "行内代码", text: "</>" },
  { action: "link", label: "链接", title: "插入链接", text: "↗" },
  { action: "heading", label: "标题", title: "转换为二级标题", text: "H2" },
  { action: "blockquote", label: "引用", title: "转换为引用", text: "❝" },
  { action: "bulletList", label: "项目符号列表", title: "项目符号列表", text: "•" },
  { action: "numberedList", label: "编号列表", title: "编号列表", text: "1." },
  { action: "inlineMath", label: "行内公式", title: "行内公式", text: "$x$" },
  { action: "displayMath", label: "块级公式", title: "块级公式", text: "$$" },
  { action: "alignedMath", label: "多行公式", title: "多行公式", text: "Align" },
];

interface EditingBlock {
  index: number;
  value: string;
  baseBody: string;
}

export function MarkdownBlockEditor({
  content,
  onChange,
  onSelectionChange,
  onBlur,
  onNavigate,
}: {
  content: string;
  onChange: (value: string) => void;
  onSelectionChange: (value: string) => void;
  onBlur: () => void;
  onNavigate: (path: string) => void;
}) {
  const envelope = useMemo(() => splitMarkdownFrontmatter(content), [content]);
  const parsed = useMemo(() => parseMarkdownBlocks(envelope.body), [envelope.body]);
  const [mode, setMode] = useState<"blocks" | "source">("blocks");
  const [editing, setEditing] = useState<EditingBlock | null>(null);
  const blocksForView = editing ? parseMarkdownBlocks(editing.baseBody).blocks : parsed.blocks;
  const viewBlocks = editing && editing.index >= blocksForView.length
    ? [...blocksForView, { id: "new-block", type: "other" as const, start: envelope.body.length, end: envelope.body.length, raw: "", separator: "" }]
    : blocksForView;
  const blockEditorRef = useRef<HTMLTextAreaElement>(null);
  const sourceEditorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) blockEditorRef.current?.focus();
  }, [editing?.index]);

  function startEditing(index: number, value: string) {
    setEditing({ index, value, baseBody: envelope.body });
  }

  function updateBlock(value: string) {
    if (!editing) return;
    setEditing({ ...editing, value });
    onChange(envelope.frontmatter + replaceMarkdownBlock(editing.baseBody, editing.index, value));
  }

  function addBlock() {
    setEditing({ index: parsed.blocks.length, value: "", baseBody: envelope.body });
  }

  function setSource(value: string) {
    onChange(value);
    const selected = sourceEditorRef.current;
    if (selected) onSelectionChange(value.slice(selected.selectionStart, selected.selectionEnd));
  }

  function format(action: MarkdownFormattingAction) {
    if (mode === "blocks" && editing) {
      const editor = blockEditorRef.current;
      if (!editor) return;
      const result = applyMarkdownFormatting(editing.value, editor.selectionStart, editor.selectionEnd, action);
      updateBlock(result.value);
      requestAnimationFrame(() => {
        blockEditorRef.current?.focus();
        blockEditorRef.current?.setSelectionRange(result.selectionStart, result.selectionEnd);
      });
      return;
    }
    if (mode !== "source") return;
    const editor = sourceEditorRef.current;
    if (!editor || editor.selectionStart < envelope.frontmatter.length || editor.selectionEnd < envelope.frontmatter.length) return;
    const start = editor.selectionStart - envelope.frontmatter.length;
    const end = editor.selectionEnd - envelope.frontmatter.length;
    const result = applyMarkdownFormatting(envelope.body, start, end, action);
    onChange(envelope.frontmatter + result.value);
    requestAnimationFrame(() => {
      sourceEditorRef.current?.focus();
      sourceEditorRef.current?.setSelectionRange(
        envelope.frontmatter.length + result.selectionStart,
        envelope.frontmatter.length + result.selectionEnd,
      );
    });
  }

  const sourceSelectionIsInBody = mode === "source"
    && Boolean(sourceEditorRef.current)
    && (sourceEditorRef.current?.selectionStart ?? 0) >= envelope.frontmatter.length
    && (sourceEditorRef.current?.selectionEnd ?? 0) >= envelope.frontmatter.length;
  const canFormat = mode === "source" ? sourceSelectionIsInBody : Boolean(editing);

  return <div className="markdown-workspace-editor">
    <div className="markdown-editor-heading">
      <SectionHeading title="Markdown 正文" detail="双击区块或使用编辑按钮；编辑时会即时显示阅读预览。" />
      <button
        className="button button-secondary"
        type="button"
        aria-pressed={mode === "source"}
        onClick={() => { setMode(mode === "source" ? "blocks" : "source"); setEditing(null); }}
      >{mode === "source" ? "区块编辑" : "完整源码"}</button>
    </div>
    <div className="markdown-toolbar" role="toolbar" aria-label="Markdown 格式工具" onMouseDown={(event) => event.preventDefault()}>
      {formattingActions.map(({ action, label, title, text }, index) => <span className={index === 9 ? "toolbar-group-start" : undefined} key={action}>
        <button type="button" aria-label={label} title={title} disabled={!canFormat} onClick={() => format(action)}>{text}</button>
      </span>)}
      {!canFormat && <small>{mode === "source" ? "请选择正文中的文字或光标" : "先编辑一个区块"}</small>}
    </div>

    {mode === "source" ? <div className="markdown-source-layout">
      <textarea
        ref={sourceEditorRef}
        className="knowledge-editor"
        value={content}
        onChange={(event) => setSource(event.target.value)}
        onSelect={(event) => onSelectionChange(event.currentTarget.value.slice(event.currentTarget.selectionStart, event.currentTarget.selectionEnd))}
        onBlur={onBlur}
        spellCheck={false}
        aria-label="Markdown 完整源码"
      />
      <section className="markdown-live-preview">
        <SectionHeading title="即时预览" detail="使用 Reference Hub 阅读端的渲染方式" />
        <Suspense fallback={<p className="subtle-copy">正在生成预览…</p>}><MarkdownContent content={envelope.body} onNavigate={onNavigate} /></Suspense>
      </section>
    </div> : <>
      <div className="markdown-block-list">
        {viewBlocks.map((block, index) => editing?.index === index ? <div className="markdown-block-edit" key={`edit:${block.id}`}>
          <textarea
            ref={blockEditorRef}
            className="knowledge-editor markdown-block-textarea"
            value={editing.value}
            onChange={(event) => updateBlock(event.target.value)}
            onSelect={(event) => onSelectionChange(event.currentTarget.value.slice(event.currentTarget.selectionStart, event.currentTarget.selectionEnd))}
            onBlur={onBlur}
            spellCheck={false}
            aria-label={`Markdown 区块 ${index + 1}`}
          />
          <div className="markdown-live-preview markdown-block-live-preview">
            <SectionHeading title="即时预览" />
            <Suspense fallback={<p className="subtle-copy">正在生成预览…</p>}><MarkdownContent content={editing.value} onNavigate={onNavigate} /></Suspense>
          </div>
          <div className="markdown-block-actions"><button className="button button-secondary" type="button" onClick={() => setEditing(null)}>完成区块</button></div>
        </div> : <article className="markdown-block" key={block.id} onDoubleClick={() => startEditing(index, block.raw)}>
          <div className="markdown-block-content"><Suspense fallback={<p className="subtle-copy">正在生成预览…</p>}><MarkdownContent content={block.raw} onNavigate={onNavigate} /></Suspense></div>
          <button className="text-button markdown-block-edit-button" type="button" onClick={() => startEditing(index, block.raw)}>编辑区块</button>
        </article>)}
        {!viewBlocks.length && <p className="markdown-empty-state">正文为空。添加一个 Markdown 区块开始写作。</p>}
      </div>
      <button className="markdown-add-block" type="button" onClick={addBlock}>＋ 添加 Markdown 区块</button>
    </>}
  </div>;
}
