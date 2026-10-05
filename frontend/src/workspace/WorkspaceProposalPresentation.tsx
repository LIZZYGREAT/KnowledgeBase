import { lazy, Suspense } from "react";
import type { Proposal } from "../api";
import { Chip } from "../ui";

const MarkdownContent = lazy(() => import("../Markdown").then((module) => ({ default: module.MarkdownContent })));

type Data = Record<string, unknown>;

function asRecord(value: unknown): Data | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Data : null;
}

function MarkdownSection({ title, content }: { title: string; content: string }) {
  return <section className="proposal-result-section">
    <h4>{title}</h4>
    <Suspense fallback={<p className="subtle-copy">正在生成阅读视图…</p>}><MarkdownContent content={content} /></Suspense>
  </section>;
}

function DocumentReview({ result }: { result: Data }) {
  const findings = Array.isArray(result.findings) ? result.findings.map(asRecord).filter((item): item is Data => item !== null) : [];
  const summary = typeof result.summary === "string" ? result.summary : "";
  const proposedContent = typeof result.proposed_content === "string" ? result.proposed_content : "";
  const rationale = typeof result.rationale === "string" ? result.rationale : "";
  return <>
    {summary && <MarkdownSection title="Review summary" content={summary} />}
    {rationale && <MarkdownSection title="Rationale" content={rationale} />}
    {proposedContent && <MarkdownSection title="Suggested revision" content={proposedContent} />}
    {findings.length > 0 && <section className="proposal-result-section">
      <h4>Findings</h4>
      <div className="proposal-result-list">{findings.map((finding, index) => <article className="proposal-result-item" key={`${String(finding.topic ?? "finding")}:${index}`}>
        <strong>{typeof finding.topic === "string" ? finding.topic : `Finding ${index + 1}`}</strong>
        {typeof finding.severity === "string" && <Chip tone={finding.severity === "warning" ? "amber" : undefined}>{finding.severity}</Chip>}
        {typeof finding.explanation === "string" && <MarkdownSection title="Explanation" content={finding.explanation} />}
        {typeof finding.suggestion === "string" && <MarkdownSection title="Suggestion" content={finding.suggestion} />}
      </article>)}</div>
    </section>}
  </>;
}

function MetadataSuggestion({ result }: { result: Data }) {
  const changes = asRecord(result.changes);
  const rationale = typeof result.rationale === "string" ? result.rationale : "";
  const labels: Record<string, string> = {
    title: "Title",
    type: "Document type",
    domains: "Domains",
    topics: "Topics",
    tags: "Tags",
    sources: "Sources",
  };
  return <>
    {rationale && <MarkdownSection title="Rationale" content={rationale} />}
    {changes && <dl className="proposal-metadata-changes">{Object.entries(changes).map(([key, value]) => {
      if (!labels[key]) return null;
      const values = Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : typeof value === "string" ? [value] : [];
      if (!values.length) return null;
      return <div key={key}><dt>{labels[key]}</dt><dd>{values.map((item) => <Chip key={item}>{item}</Chip>)}</dd></div>;
    })}</dl>}
  </>;
}

function TermDraft({ result }: { result: Data }) {
  const aliases = Array.isArray(result.aliases) ? result.aliases.filter((item): item is string => typeof item === "string") : [];
  const definition = typeof result.definition === "string" ? result.definition : "";
  return <>
    {typeof result.title === "string" && <h3 className="proposal-term-title">{result.title}</h3>}
    <dl className="proposal-term-metadata">
      {typeof result.id === "string" && <div><dt>ID</dt><dd>{result.id}</dd></div>}
      {typeof result.type === "string" && <div><dt>Type</dt><dd>{result.type}</dd></div>}
      {typeof result.depth === "string" && <div><dt>Depth</dt><dd>{result.depth}</dd></div>}
      {aliases.length > 0 && <div><dt>Aliases</dt><dd>{aliases.map((alias) => <Chip key={alias}>{alias}</Chip>)}</dd></div>}
    </dl>
    {definition && <MarkdownSection title="Definition" content={definition} />}
  </>;
}

function EvidenceSuggestions({ result }: { result: Data }) {
  const candidates = Array.isArray(result.candidates) ? result.candidates.map(asRecord).filter((item): item is Data => item !== null) : [];
  return <div className="proposal-result-list">{candidates.map((candidate, index) => <article className="proposal-result-item" key={`${String(candidate.source_id ?? "source")}:${index}`}>
    {typeof candidate.source_id === "string" && <strong>Source · {candidate.source_id}</strong>}
    {typeof candidate.claim === "string" && <MarkdownSection title="Claim" content={candidate.claim} />}
    {typeof candidate.rationale === "string" && <MarkdownSection title="Why this Source" content={candidate.rationale} />}
  </article>)}</div>;
}

function TermCandidates({ result }: { result: Data }) {
  const candidates = Array.isArray(result.candidates) ? result.candidates.map(asRecord).filter((item): item is Data => item !== null) : [];
  return <div className="proposal-result-list">{candidates.map((candidate, index) => <article className="proposal-result-item" key={`${String(candidate.mention ?? "term")}:${index}`}>
    <strong>{typeof candidate.mention === "string" ? candidate.mention : `Term ${index + 1}`}</strong>
    {typeof candidate.action === "string" && <p>{candidate.action === "link_existing" ? "Link to an existing Term" : "Propose a new Term"}{typeof candidate.term_id === "string" ? ` · ${candidate.term_id}` : ""}</p>}
    {typeof candidate.rationale === "string" && <MarkdownSection title="Rationale" content={candidate.rationale} />}
  </article>)}</div>;
}

function HumanResult({ proposal }: { proposal: Proposal }) {
  const result = asRecord(proposal.payload.result);
  const content = typeof proposal.payload.content === "string" ? proposal.payload.content : "";
  if (!result) return content ? <MarkdownSection title="Suggested content" content={content} /> : <p className="subtle-copy">No readable proposal summary is available.</p>;

  switch (proposal.kind) {
    case "metadata": return <MetadataSuggestion result={result} />;
    case "document_revision":
    case "format": return <DocumentReview result={result} />;
    case "new_term": return <TermDraft result={result} />;
    case "evidence": return <EvidenceSuggestions result={result} />;
    case "link": return <TermCandidates result={result} />;
    default: {
      const proposed = typeof result.proposed_content === "string" ? result.proposed_content : content;
      return <>
        {typeof result.summary === "string" && <MarkdownSection title="Summary" content={result.summary} />}
        {typeof result.rationale === "string" && <MarkdownSection title="Rationale" content={result.rationale} />}
        {proposed && <MarkdownSection title="Suggested content" content={proposed} />}
        {!proposed && typeof result.summary !== "string" && typeof result.rationale !== "string" && <p className="subtle-copy">This Proposal has no readable summary. Open the raw data to inspect its fields.</p>}
      </>;
    }
  }
}

export function WorkspaceProposalPresentation({ proposal }: { proposal: Proposal }) {
  const rawData = proposal.payload.result ?? proposal.payload;
  return <>
    <div className="proposal-human-view"><HumanResult proposal={proposal} /></div>
    <details className="proposal-raw-data">
      <summary>查看原始 JSON</summary>
      <pre className="proposal-payload">{JSON.stringify(rawData, null, 2)}</pre>
    </details>
  </>;
}
