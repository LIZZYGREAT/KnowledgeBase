import type { DragEvent } from "react";
import type { CollectionNode, CollectionSectionNode, EntityType } from "../api";
import { Chip } from "../ui";
import { countEntities, sectionKey } from "./explorerModel";
interface CollectionTreeProps {
  nodes: CollectionNode[];
  collectionId: string;
  selectedEntity?: { type: EntityType; id: string };
  expandedSections: string[] | null;
  filter: string;
  onToggle: (sectionId: string) => void;
  onOpen: (type: EntityType, id: string) => void;
  editMode: boolean;
  onStartDrag: (event: DragEvent<HTMLElement>, node: CollectionNode) => void;
  onDrop: (event: DragEvent<HTMLElement>, parentSectionId: string | null, beforeNodeId?: string | null) => void;
  onRemove: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  onProgress: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  canUpdateProgress: (node: Extract<CollectionNode, { kind: "entity" }>) => boolean;
  onCopy: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  onAddExisting: (parentSectionId: string | null) => void;
  onNewSection: (parentSectionId: string | null) => void;
  onRenameSection: (node: CollectionSectionNode) => void;
  onMoveSibling: (nodeId: string, direction: number) => void;
  onDeleteSection: (node: CollectionSectionNode) => void;
  onNewNoteHere: (sectionId: string, sectionTitle: string) => void;
}

export function CollectionTree(props: CollectionTreeProps) {
  const { nodes, collectionId, expandedSections, filter, editMode, onDrop } = props;
  return <ul
    className="explorer-tree"
    role="tree"
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, null); }}
  >
    {nodes.map((node) => node.kind === "section" ? <SectionTreeNode key={node.id} node={node} collectionId={collectionId} expandedSections={expandedSections} filter={filter} props={props} /> : <EntityTreeNode key={node.id} node={node} props={props} parentSectionId={null} />)}
    {!nodes.length && <li className="explorer-tree-empty" onDragOver={(event) => { if (editMode) event.preventDefault(); }} onDrop={(event) => { if (editMode) onDrop(event, null); }}>{filter ? "没有匹配项目" : editMode ? "拖放知识条目到这里，或使用 Add Existing。" : "这个 Collection 还没有内容。"}</li>}
  </ul>;
}

function SectionTreeNode({
  node,
  collectionId,
  expandedSections,
  filter,
  props,
}: {
  node: CollectionSectionNode;
  collectionId: string;
  expandedSections: string[] | null;
  filter: string;
  props: CollectionTreeProps;
}) {
  const { editMode, onToggle, onDrop } = props;
  const key = sectionKey(collectionId, node.id);
  const expanded = Boolean(filter.trim()) || expandedSections === null || expandedSections.includes(key);
  return <li
    className="explorer-tree-section"
    role="treeitem"
    aria-expanded={expanded}
    draggable={editMode}
    onDragStart={(event) => props.onStartDrag(event, node)}
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, node.id); }}
  >
    <div className="explorer-section-row">
      <button className="explorer-section-toggle" aria-expanded={expanded} onClick={() => onToggle(node.id)}>
        <span className={`explorer-chevron ${expanded ? "expanded" : ""}`} aria-hidden="true">›</span>
        <span>{node.title}</span>
        <small>{countEntities(node.children)}</small>
      </button>
      {editMode && <div className="explorer-node-actions">
        <button title="Add existing Entity" aria-label={`在 ${node.title} 中添加已有 Entity`} onClick={() => props.onAddExisting(node.id)}>⊕</button>
        <button title="New Note Here" aria-label={`在 ${node.title} 中新建笔记`} onClick={() => props.onNewNoteHere(node.id, node.title)}>N</button>
        <button title="Add nested Section" aria-label={`在 ${node.title} 中新建 Section`} onClick={() => props.onNewSection(node.id)}>＋</button>
        <button title="Move up" aria-label={`上移 ${node.title}`} onClick={() => props.onMoveSibling(node.id, -1)}>↑</button>
        <button title="Move down" aria-label={`下移 ${node.title}`} onClick={() => props.onMoveSibling(node.id, 1)}>↓</button>
        <button title="Rename Section" aria-label={`重命名 ${node.title}`} onClick={() => props.onRenameSection(node)}>✎</button>
        <button title="Delete Section" aria-label={`删除 ${node.title}`} onClick={() => props.onDeleteSection(node)}>×</button>
      </div>}
    </div>
    {expanded && <ul
      className="explorer-tree explorer-tree-children"
      role="group"
      onDragOver={(event) => { if (editMode) event.preventDefault(); }}
      onDrop={(event) => { if (editMode) onDrop(event, node.id); }}
    >
      {node.children.map((child) => child.kind === "section" ? <SectionTreeNode key={child.id} node={child} collectionId={collectionId} expandedSections={expandedSections} filter={filter} props={props} /> : <EntityTreeNode key={child.id} node={child} props={props} parentSectionId={node.id} />)}
      {editMode && !node.children.length && <li className="explorer-drop-hint">Drop here</li>}
    </ul>}
  </li>;
}

function EntityTreeNode({
  node,
  props,
  parentSectionId,
}: {
  node: Extract<CollectionNode, { kind: "entity" }>;
  props: CollectionTreeProps;
  parentSectionId: string | null;
}) {
  const { editMode, onDrop } = props;
  const selected = props.selectedEntity?.type === node.entity_type && props.selectedEntity.id === node.entity_id;
  const icon = node.entity_type === "document" ? "D" : node.entity_type === "term" ? "T" : "S";
  const progressLabel = node.progress === "done" ? "继续阅读" : node.progress === "reading" ? "标为已读" : "开始阅读";
  return <li
    className={`explorer-tree-entity ${selected ? "explorer-tree-entity-selected" : ""}`}
    role="treeitem"
    aria-current={selected ? "page" : undefined}
    draggable={editMode}
    onDragStart={(event) => props.onStartDrag(event, node)}
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, parentSectionId, node.id); }}
  >
    <div className="explorer-entity-row">
      <button className="explorer-entity-link" onClick={() => props.onOpen(node.entity_type, node.entity_id)}>
        <span className={`explorer-entity-icon explorer-entity-${node.entity_type}`}>{icon}</span>
        <span className="explorer-entity-copy"><strong>{node.title || node.entity_id}</strong><small>{node.entity_id}</small></span>
        {node.progress && <Chip tone={node.progress === "done" ? "green" : "blue"}>{node.progress === "done" ? "已读" : "在读"}</Chip>}
      </button>
      <div className="explorer-node-actions">
        {node.entity_type === "document" && <button title={props.canUpdateProgress(node) ? progressLabel : "发布此引用后即可跟踪阅读进度"} aria-label={`${progressLabel}：${node.title}`} disabled={!props.canUpdateProgress(node)} onClick={() => props.onProgress(node)}>{node.progress === "done" ? "↻" : node.progress === "reading" ? "✓" : "◷"}</button>}
        {editMode && <>
          <button title="Copy to Collection" aria-label={`复制 ${node.title} 到其他 Collection`} onClick={() => props.onCopy(node)}>⧉</button>
          <button title="Remove reference" aria-label={`从 Collection 移除 ${node.title}`} onClick={() => props.onRemove(node)}>×</button>
        </>}
      </div>
    </div>
  </li>;
}
