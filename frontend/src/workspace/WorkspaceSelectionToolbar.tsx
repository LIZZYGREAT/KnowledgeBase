import type { AnnotationStyleType } from "../api";
import type { MarkdownFormattingAction } from "../markdownFormatting.js";

const formats: Array<{ action: MarkdownFormattingAction; label: string; icon: string }> = [
  { action: "bold", label: "加粗", icon: "B" },
  { action: "italic", label: "斜体", icon: "I" },
  { action: "code", label: "行内代码", icon: "</>" },
  { action: "link", label: "链接", icon: "↗" },
  { action: "heading", label: "标题", icon: "H2" },
  { action: "blockquote", label: "引用", icon: "❝" },
  { action: "bulletList", label: "项目符号列表", icon: "•" },
  { action: "numberedList", label: "编号列表", icon: "1." },
];

const highlights = ["yellow", "green", "blue", "pink", "gray"] as const;
const textColors = ["red", "orange", "green", "blue", "purple", "muted"] as const;

export function WorkspaceSelectionToolbar({
  selectedText,
  top,
  left,
  formatDisabled,
  canAnnotate,
  annotationBusy,
  aiDisabled = false,
  onFormat,
  onAnnotate,
  onClear,
  onAskAI,
}: {
  selectedText: string;
  top: number;
  left: number;
  formatDisabled: boolean;
  canAnnotate: boolean;
  annotationBusy: boolean;
  aiDisabled?: boolean;
  onFormat: (action: MarkdownFormattingAction) => void;
  onAnnotate: (styleType: AnnotationStyleType, styleValue: string | null) => void;
  onClear: () => void;
  onAskAI?: () => void;
}) {
  return <div className="annotation-toolbar workspace-selection-toolbar" role="toolbar" aria-label={`选中文本工具：${selectedText.slice(0, 60)}`} style={{ top, left }} onMouseDown={(event) => event.preventDefault()}>
    <div className="workspace-selection-group" role="group" aria-label="格式">
      <span className="annotation-toolbar-label">格式</span>
      {formats.map(({ action, label, icon }) => <button key={action} type="button" className="workspace-selection-format" aria-label={label} title={label} disabled={formatDisabled} onClick={() => onFormat(action)}>{icon}</button>)}
    </div>
    <span className="toolbar-divider" />
    <div className="workspace-selection-group" role="group" aria-label="标注">
      <span className="annotation-toolbar-label">标注</span>
      {highlights.map((color) => <button key={`highlight-${color}`} type="button" className={`annotation-swatch swatch-${color}`} aria-label={`${color} 高亮`} title={`${color} 高亮`} disabled={!canAnnotate || annotationBusy} onClick={() => onAnnotate("highlight", color)} />)}
      {textColors.map((color) => <button key={`text-${color}`} type="button" className={`annotation-swatch text-swatch text-${color}`} aria-label={`${color} 文字颜色`} title={`${color} 文字颜色`} disabled={!canAnnotate || annotationBusy} onClick={() => onAnnotate("text_color", color)} />)}
      <button type="button" className="annotation-underline-button" disabled={!canAnnotate || annotationBusy} onClick={() => onAnnotate("underline", null)}>下划线</button>
      <button type="button" className="annotation-clear-button" disabled={!canAnnotate || annotationBusy} onClick={onClear}>清除</button>
    </div>
    {onAskAI && <>
      <span className="toolbar-divider" />
      <div className="workspace-selection-group" role="group" aria-label="AI">
        <span className="annotation-toolbar-label">AI</span>
        <button type="button" className="workspace-selection-ai" disabled={aiDisabled} onClick={onAskAI}>Ask AI</button>
      </div>
    </>}
  </div>;
}
