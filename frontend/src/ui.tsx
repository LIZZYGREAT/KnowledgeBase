import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}

export function SectionHeading({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
      {action}
    </div>
  );
}

export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-mark" aria-hidden="true">＋</span>
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}

export function LoadingState({ label = "正在读取知识库…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="loading-dot" />
      {label}
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <strong>暂时无法载入</strong>
      <p>{message}</p>
      {retry && <button className="button button-secondary" onClick={retry}>重试</button>}
    </div>
  );
}

export function EntityRow({
  title,
  detail,
  badge,
  onClick,
}: {
  title: string;
  detail?: string;
  badge?: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="entity-row" onClick={onClick}>
      <span className="entity-row-main">
        <strong>{title}</strong>
        {detail && <span>{detail}</span>}
      </span>
      {badge}
      <span className="row-arrow" aria-hidden="true">↗</span>
    </button>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "quiet" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      className={`button button-${variant}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(date);
}

export function titleCase(value: string) {
  return value.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
