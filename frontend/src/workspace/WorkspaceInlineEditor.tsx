import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import type { PresentationAnnotation } from "../api";
import { parseMarkdownBlocks, replaceMarkdownBlock } from "../markdownBlocks.js";

const MarkdownContent = lazy(() => import("../Markdown").then((module) => ({ default: module.MarkdownContent })));

interface EditingBlock {
  index: number;
  value: string;
  baseBody: string;
  baseBlocks: ReturnType<typeof parseMarkdownBlocks>["blocks"];
}

export function WorkspaceInlineEditor({
  body,
  annotations,
  disabled = false,
  onBodyChange,
  onBeginEdit,
  onNavigate,
}: {
  body: string;
  annotations: PresentationAnnotation[];
  disabled?: boolean;
  onBodyChange: (value: string) => void;
  onBeginEdit?: () => void;
  onNavigate: (path: string) => void;
}) {
  const parsed = useMemo(() => parseMarkdownBlocks(body), [body]);
  const [editing, setEditing] = useState<EditingBlock | null>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const source = editing?.baseBody ?? body;
  const blocks = editing?.baseBlocks ?? parsed.blocks;

  useEffect(() => {
    if (editing) editorRef.current?.focus();
  }, [editing?.index]);

  function startEditing(index: number, value: string, baseBody = body, baseBlocks = parsed.blocks) {
    if (disabled || editing) return;
    onBeginEdit?.();
    setEditing({ index, value, baseBody, baseBlocks });
  }

  function updateBlock(value: string) {
    if (!editing) return;
    setEditing({ ...editing, value });
    onBodyChange(replaceMarkdownBlock(editing.baseBody, editing.index, value));
  }

  function finishEditing() {
    setEditing(null);
  }

  function cancelEditing() {
    if (editing) onBodyChange(editing.baseBody);
    setEditing(null);
  }

  const renderStateRef = useRef<{
    editing: EditingBlock | null;
    source: string;
    blocks: ReturnType<typeof parseMarkdownBlocks>["blocks"];
    disabled: boolean;
    editorRef: RefObject<HTMLTextAreaElement | null>;
    onNavigate: (path: string) => void;
    startEditing: typeof startEditing;
    updateBlock: typeof updateBlock;
    finishEditing: typeof finishEditing;
    cancelEditing: typeof cancelEditing;
  } | null>(null);
  renderStateRef.current = {
    editing, source, blocks, disabled, editorRef, onNavigate,
    startEditing, updateBlock, finishEditing, cancelEditing,
  };

  const renderBlock = useCallback((block: (typeof blocks)[number], index: number, rendered: ReactNode): ReactNode => {
    const state = renderStateRef.current;
    if (!state) return rendered;
    if (state.editing?.index === index) return <InlineBlockInput
      key={`edit:${block.id}`}
      index={index}
      value={state.editing.value}
      onChange={state.updateBlock}
      onDone={state.finishEditing}
      onCancel={state.cancelEditing}
      editorRef={state.editorRef}
      onNavigate={state.onNavigate}
      disabled={state.disabled}
    />;

    return <div className="workspace-inline-block" key={block.id} onDoubleClick={() => state.startEditing(index, block.raw, state.source, state.blocks)}>
      {rendered}
      <button
        className="workspace-inline-edit-button"
        type="button"
        aria-label={`编辑第 ${index + 1} 个区块`}
        title="编辑区块"
        disabled={state.disabled}
        onClick={() => state.startEditing(index, block.raw, state.source, state.blocks)}
      ><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.8 2.2a1.5 1.5 0 0 1 2.1 2.1L6 12.2l-3.2.8.8-3.2 8.2-7.6Z" /><path d="m10.7 3.3 2.1 2.1" /></svg></button>
    </div>;
  }, []);

  const appendBlock = editing?.index === blocks.length;
  return <div className="workspace-inline-editor">
    <div className={`workspace-inline-rendered ${editing ? "is-editing" : ""}`}>
      <Suspense fallback={<p className="subtle-copy">正在生成阅读视图…</p>}>
        <MarkdownContent
          content={source}
          onNavigate={onNavigate}
          annotations={annotations}
          blockRanges={blocks}
          renderBlock={renderBlock}
        />
      </Suspense>
      {appendBlock && <InlineBlockInput
        index={editing.index}
        value={editing.value}
        onChange={updateBlock}
        onDone={finishEditing}
        onCancel={cancelEditing}
        editorRef={editorRef}
        onNavigate={onNavigate}
        disabled={disabled}
      />}
    </div>
    {!editing && <button className="workspace-inline-add-button" type="button" disabled={disabled} onClick={() => startEditing(parsed.blocks.length, "")}>＋ 添加 Markdown 区块</button>}
    {!parsed.blocks.length && !editing && <p className="markdown-empty-state">正文为空。添加一个 Markdown 区块开始写作。</p>}
  </div>;
}

function InlineBlockInput({
  index,
  value,
  onChange,
  onDone,
  onCancel,
  editorRef,
  onNavigate,
  disabled,
}: {
  index: number;
  value: string;
  onChange: (value: string) => void;
  onDone: () => void;
  onCancel: () => void;
  editorRef: RefObject<HTMLTextAreaElement | null>;
  onNavigate: (path: string) => void;
  disabled: boolean;
}) {
  return <section className="workspace-inline-block workspace-inline-block-editing" aria-label={`编辑第 ${index + 1} 个 Markdown 区块`}>
    <textarea
      ref={editorRef}
      className="knowledge-editor workspace-inline-textarea"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") onDone();
        if (event.key === "Escape") onCancel();
      }}
      spellCheck={false}
      aria-label={`Markdown 区块 ${index + 1}`}
    />
    <div className="workspace-inline-preview"><Suspense fallback={<p className="subtle-copy">正在生成预览…</p>}><MarkdownContent content={value} onNavigate={onNavigate} /></Suspense></div>
    <div className="workspace-inline-actions"><span>Ctrl/Cmd + Enter 完成 · Esc 还原</span><button className="button button-primary" type="button" disabled={disabled} onClick={onDone}>完成区块</button></div>
  </section>;
}
