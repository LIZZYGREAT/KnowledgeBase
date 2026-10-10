import { useEffect, useState } from "react";
import { parseDocument } from "yaml";
import { applyProposalToDraft, discardDraft, listProposals, preflightDraft, publishDraft, rejectProposal, rejectTermCandidate, requestCandidateTermDraftProposal, requestTermRewrite, type Draft, type Proposal, type TermCandidate } from "../api";
import { useRuntimeDraftSession } from "../draft/useRuntimeDraftSession";
import { MarkdownContent } from "../Markdown";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { termLanguageSections, type TermLanguage } from "../termLanguage";
import { errorMessage } from "../errors";

type ReviewAction = "generate" | "rewrite" | "adopt" | "discard" | "approve" | "reject";

export function TermCandidateReview({ candidate, seed, onDone }: { candidate: TermCandidate; seed: Draft; onDone: (warnings?: string[]) => void }) {
  const session = useRuntimeDraftSession({ entityType: "term", entityId: seed.entity_id, enabled: true, initialContent: seed.content, initialContentReady: true });
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busyAction, setBusyAction] = useState<ReviewAction | null>(null);
  const [error, setError] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");
  const [requirements, setRequirements] = useState("");
  const [language, setLanguage] = useState<TermLanguage>("zh");
  const [editing, setEditing] = useState(false);
  const envelope = splitMarkdownFrontmatter(session.content);
  const proposedBody = proposal && typeof proposal.payload.content === "string" ? splitMarkdownFrontmatter(proposal.payload.content).body : "";
  const sections = termLanguageSections(envelope.body);
  const hasLanguageExplanation = Boolean(sections.zh || sections.en);
  const rewriteBlockedReason = proposal
    ? "请先将当前建议采用到 Draft，或放弃建议，再重写。"
    : !hasLanguageExplanation
      ? "请先填写或生成至少一种语言的解释。"
      : !requirements.trim()
        ? "请输入重写要求。"
        : "";
  const locked = Boolean(busyAction) || session.loading || session.state === "runtime-conflict";

  useEffect(() => {
    let active = true;
    void listProposals("proposed", "term", seed.entity_id).then((items) => {
      if (!active || !seed.working_content_hash) return;
      const matching = items.find((item) => item.payload.draft_id === seed.id && item.base_content_hash === seed.working_content_hash) ?? null;
      if (matching) {
        setProposal(matching);
        setActionFeedback("已载入与当前 Draft 匹配的建议；建议仍未写入 Draft。可采用、放弃或稍后继续审核。");
      }
    }).catch((reason) => { if (active) setError(errorMessage(reason)); });
    return () => { active = false; };
  }, [seed.id, seed.content, seed.entity_id, seed.working_content_hash]);

  async function generate(rewrite: boolean) {
    if (busyAction) return;
    if (rewrite && rewriteBlockedReason) {
      setActionFeedback(rewriteBlockedReason);
      return;
    }
    setBusyAction(rewrite ? "rewrite" : "generate");
    setError("");
    setActionFeedback(rewrite ? "正在请求当前语言的重写建议…" : "正在生成双语解释建议…");
    try {
      const draft = await session.saveNow() ?? seed;
      if (rewrite) {
        const result = await requestTermRewrite(draft.id, language, requirements.trim());
        setProposal(result.proposal);
        setActionFeedback("重写建议已生成，仅供对比；当前 Draft 和正式知识尚未改变。");
      } else {
        const existing = draft.working_content_hash
          ? (await listProposals("proposed", "term", draft.entity_id)).find((item) => item.payload.draft_id === draft.id && item.base_content_hash === draft.working_content_hash)
          : undefined;
        if (existing) {
          setProposal(existing);
          setActionFeedback("已复用与当前 Draft 内容匹配的双语建议；没有重复请求 AI。");
        } else {
          setProposal((await requestCandidateTermDraftProposal(draft.id, candidate.id)).proposal);
          setActionFeedback("双语解释建议已生成，仅供对比；当前 Draft 和正式知识尚未改变。");
        }
      }
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("操作失败。已保留当前编辑和建议内容，可检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function adopt() {
    if (!proposal) return null;
    const draft = await session.saveNow() ?? seed;
    const result = await applyProposalToDraft(proposal.id, draft.id, draft.revision);
    session.acceptDraft(result.draft);
    setProposal(null);
    setActionFeedback("建议已采用到 Term Draft；仍需检查并单独发布。");
    return result.draft;
  }

  async function discardSuggestion() {
    if (!proposal || busyAction) return;
    setBusyAction("discard");
    setError("");
    setActionFeedback("正在放弃这条建议…");
    try {
      await rejectProposal(proposal.id);
      setProposal(null);
      setActionFeedback("建议已放弃；Term Draft 未被修改。");
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("放弃失败；建议仍保留在当前页面。");
    } finally {
      setBusyAction(null);
    }
  }

  async function approve() {
    if (busyAction) return;
    setBusyAction("approve");
    setError("");
    setActionFeedback("正在检查 Draft 并准备发布…");
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
      setActionFeedback("Draft 已保存，正在运行 Preflight…");
      const preflight = await preflightDraft(draft.id);
      if (!preflight.valid || preflight.conflict) throw new Error([...preflight.errors, ...preflight.warnings].join("；") || "发布冲突，请打开完整编辑器处理。");
      setActionFeedback("Preflight 通过，正在由 Publisher 发布…");
      const published = await publishDraft(draft.id, draft.revision);
      setActionFeedback("Term 已正式发布。");
      onDone(published.warnings);
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("发布未完成；Draft 与输入仍保留，可修复后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function reject() {
    if (busyAction) return;
    setBusyAction("reject");
    setError("");
    setActionFeedback("正在保存 Draft 并拒绝此建议…");
    try {
      const draft = await session.saveNow() ?? seed;
      await discardDraft(draft.id, draft.revision);
      await rejectTermCandidate(candidate.id, { scope: "global" });
      setActionFeedback("Term 建议已拒绝。");
      onDone();
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("拒绝未完成；请检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  return <section className="term-candidate-inline-review" aria-label="候选解释审核">
    <div className="term-candidate-edit-actions" role="group" aria-label="编辑或生成解释">
      <button type="button" className="button button-secondary" disabled={locked} onClick={() => setEditing(!editing)}>{editing ? "完成编辑" : "编辑"}</button>
      <button type="button" className="button button-primary" disabled={locked} onClick={() => void generate(false)}>{busyAction === "generate" ? "正在生成…" : "AI 生成双语解释"}</button>
    </div>
    <p className="subtle-copy">显式生成会将当前 Term Draft、候选摘录和必要注册表发送给 DeepSeek；已有匹配建议会复用，AI 结果不会自动采用或发布。</p>
    {editing && <label className="field-label">Markdown 源码<textarea disabled={locked} value={envelope.body} rows={10} onChange={(event) => { const body = event.target.value; session.updateContent(envelope.frontmatter + (/^# /m.test(body) ? body : `# ${candidate.display_name}\n\n${body}`)); setProposal(null); setActionFeedback("编辑内容只保存在 Draft；正式知识尚未改变。"); }} /></label>}
    <div className="term-candidate-current-preview"><strong>当前 Term Draft</strong><MarkdownContent content={envelope.body} /></div>
    <div className="term-candidate-rewrite-controls">
      <label className="field-label">AI 重写要求<textarea disabled={locked} rows={2} value={requirements} onChange={(event) => setRequirements(event.target.value)} placeholder="例如：解释向量维度、来源和分类器的使用方式，并给一个简单例子" /></label>
      <label className="field-label">重写语言<select disabled={locked} value={language} onChange={(event) => setLanguage(event.target.value as TermLanguage)}><option value="zh">中文</option><option value="en">English</option></select></label>
      <button type="button" className="button button-secondary" disabled={locked || Boolean(rewriteBlockedReason)} onClick={() => void generate(true)}>{busyAction === "rewrite" ? "正在重写…" : "AI 重写"}</button>
      {rewriteBlockedReason && !busyAction && <p className="term-candidate-disabled-reason" role="status">{rewriteBlockedReason}</p>}
    </div>
    {proposal && <details className="term-candidate-proposal-comparison" open>
      <summary>原文与 AI 建议对比</summary>
      <div className="term-candidate-comparison-grid">
        <section aria-label="当前 Term Draft 原文"><h4>当前 Term Draft</h4><div className="term-candidate-comparison-body"><MarkdownContent content={withoutLeadingTitle(envelope.body)} /></div></section>
        <section aria-label="尚未采用的 AI 建议"><h4>AI 建议 · 尚未采用</h4><div className="term-candidate-comparison-body"><MarkdownContent content={withoutLeadingTitle(proposedBody)} /></div></section>
      </div>
      <div className="term-candidate-suggestion-actions" role="group" aria-label="建议操作">
        <button type="button" className="button button-primary" disabled={locked} onClick={() => { setBusyAction("adopt"); setError(""); setActionFeedback("正在将建议写入 Draft…"); void adopt().catch((reason) => { setError(errorMessage(reason)); setActionFeedback("采用失败；建议仍保留，可检查错误后重试。"); }).finally(() => setBusyAction(null)); }}>{busyAction === "adopt" ? "正在采用…" : "采用到 Draft"}</button>
        <button type="button" className="button button-danger" disabled={locked} onClick={() => void discardSuggestion()}>{busyAction === "discard" ? "正在放弃…" : "放弃建议"}</button>
      </div>
    </details>}
    <div className="term-candidate-decision-actions" role="group" aria-label="审核决定">
      <button type="button" className="button button-primary" disabled={locked || !(proposedBody || envelope.body.replace(/^#+.*$/gm, "").trim())} onClick={() => void approve()}>{busyAction === "approve" ? "正在发布…" : "通过"}</button>
      <button type="button" className="button button-danger" disabled={locked} onClick={() => void reject()}>{busyAction === "reject" ? "正在拒绝…" : "拒绝"}</button>
    </div>
    {actionFeedback && <p className="term-candidate-action-feedback" role="status">{actionFeedback}</p>}
    {(error || session.error) && <p role="alert" className="error-copy">{error || session.error}</p>}
  </section>;
}

function withoutLeadingTitle(body: string): string {
  return body.replace(/^# [^\r\n]*(?:\r?\n)+/, "");
}
