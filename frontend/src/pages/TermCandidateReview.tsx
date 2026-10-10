import { useEffect, useState } from "react";
import { parseDocument } from "yaml";
import { applyProposalToDraft, discardDraft, listProposals, preflightDraft, publishDraft, rejectTermCandidate, requestCandidateTermDraftProposal, requestTermRewrite, type Draft, type Proposal, type TermCandidate } from "../api";
import { useRuntimeDraftSession } from "../draft/useRuntimeDraftSession";
import { MarkdownContent } from "../Markdown";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { termLanguageSections, type TermLanguage } from "../termLanguage";
import { hashText } from "../reader/readerModel";
import { errorMessage } from "../errors";

export function TermCandidateReview({ candidate, seed, onDone }: { candidate: TermCandidate; seed: Draft; onDone: () => void }) {
  const session = useRuntimeDraftSession({ entityType: "term", entityId: seed.entity_id, enabled: true, initialContent: seed.content, initialContentReady: true });
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [requirements, setRequirements] = useState("");
  const [language, setLanguage] = useState<TermLanguage>("zh");
  const [editing, setEditing] = useState(false);
  const envelope = splitMarkdownFrontmatter(session.content);
  const proposedBody = proposal && typeof proposal.payload.content === "string" ? splitMarkdownFrontmatter(proposal.payload.content).body : "";
  useEffect(() => {
    let active = true;
    void listProposals("proposed", "term", seed.entity_id).then(async (items) => {
      const hash = await hashText(seed.content);
      if (active) setProposal(items.find((item) => item.payload.draft_id === seed.id && item.base_content_hash === hash) ?? null);
    }).catch((reason) => { if (active) setError(errorMessage(reason)); });
    return () => { active = false; };
  }, [seed.id, seed.content, seed.entity_id]);
  async function generate(rewrite: boolean) {
    setBusy(true); setError("");
    try {
      const draft = await session.saveNow() ?? seed;
      if (rewrite) {
        setProposal((await requestTermRewrite(draft.id, language, requirements)).proposal);
      } else {
        const hash = await hashText(draft.content);
        const existing = (await listProposals("proposed", "term", draft.entity_id)).find((item) => item.payload.draft_id === draft.id && item.base_content_hash === hash);
        setProposal(existing ?? (await requestCandidateTermDraftProposal(draft.id, candidate.id)).proposal);
      }
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  async function adopt() {
    if (!proposal) return;
    const draft = await session.saveNow() ?? seed;
    const result = await applyProposalToDraft(proposal.id, draft.id, draft.revision);
    session.acceptDraft(result.draft); setProposal(null);
    return result.draft;
  }
  async function approve() {
    setBusy(true); setError("");
    try {
      const adopted = proposal ? await adopt() : null;
      const current = adopted?.content ?? session.getCurrentContent();
      const parts = splitMarkdownFrontmatter(current);
      if (!parts.body.replace(/^#+.*$/gm, "").trim()) throw new Error("请先生成解释或人工填写，不能批准空白 Term。");
      const metadata = parseDocument(parts.frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, ""));
      metadata.setIn(["review", "human", "status"], "approved");
      session.updateContent(`---\n${metadata.toString()}---\n${parts.body}`);
      const draft = await session.saveNow();
      if (!draft) throw new Error("Draft 保存失败，请重试。");
      const preflight = await preflightDraft(draft.id);
      if (!preflight.valid || preflight.conflict) throw new Error([...preflight.errors, ...preflight.warnings].join("；") || "发布冲突，请打开完整编辑器处理。");
      await publishDraft(draft.id, draft.revision);
      onDone();
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  async function reject() {
    setBusy(true); setError("");
    try {
      const draft = await session.saveNow() ?? seed;
      await discardDraft(draft.id, draft.revision);
      await rejectTermCandidate(candidate.id, { scope: "global" });
      onDone();
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  const locked = busy || session.loading || session.state === "runtime-conflict";
  const sections = termLanguageSections(envelope.body);
  return <section className="term-candidate-inline-review" aria-label="候选解释审核">
    <div><button disabled={locked} onClick={() => setEditing(!editing)}>编辑</button><button disabled={locked} onClick={() => void generate(false)}>生成双语解释</button></div>
    {editing && <label className="field-label">Markdown 源码<textarea value={envelope.body} rows={10} onChange={(event) => { const body = event.target.value; session.updateContent(envelope.frontmatter + (/^# /m.test(body) ? body : `# ${candidate.display_name}\n\n${body}`)); setProposal(null); }} /></label>}
    <MarkdownContent content={envelope.body} />
    <label className="field-label">AI 重写要求<input value={requirements} onChange={(event) => setRequirements(event.target.value)} /></label><select aria-label="重写语言" value={language} onChange={(event) => setLanguage(event.target.value as TermLanguage)}><option value="zh">中文</option><option value="en">English</option></select><button disabled={locked || !requirements.trim() || !(sections.zh || sections.en)} onClick={() => void generate(true)}>AI 重写</button>
    {proposal && <section aria-label="原文与新文"><p>原文 ↔ 新文</p><MarkdownContent content={proposedBody} /><button disabled={locked} onClick={() => { setBusy(true); void adopt().catch((reason) => setError(errorMessage(reason))).finally(() => setBusy(false)); }}>采用到 Draft</button><button disabled={locked} onClick={() => setProposal(null)}>放弃建议</button></section>}
    <button disabled={locked || !(proposedBody || envelope.body.replace(/^#+.*$/gm, "").trim())} onClick={() => void approve()}>通过</button><button disabled={locked} onClick={() => void reject()}>拒绝</button>
    {(error || session.error) && <p role="alert" className="error-copy">{error || session.error}</p>}
  </section>;
}
