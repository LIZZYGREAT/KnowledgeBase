import { useState } from "react";
import { MarkdownContent as Markdown } from "../Markdown";
import { rejectProposal, requestTermRewrite, type Proposal } from "../api";
import { errorMessage } from "../errors";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { replaceTermLanguage, termLanguageSections, type TermLanguage } from "../termLanguage";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import type { Navigate } from "../pages/PageShared";

export function TermLanguageCard({ body, workspace, navigate, disabled }: { body: string; workspace: WorkspaceDraftController; navigate: Navigate; disabled: boolean }) {
  const [language, setLanguage] = useState<TermLanguage>("zh");
  const [editing, setEditing] = useState(false);
  const [newLanguage, setNewLanguage] = useState(false);
  const [rewriting, setRewriting] = useState(false);
  const [requirements, setRequirements] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sections = termLanguageSections(body);
  const structured = Boolean(sections.zh || sections.en);
  const explanation = structured || newLanguage ? sections[language]?.content ?? "" : body;
  function changeExplanation(value: string) {
    const envelope = splitMarkdownFrontmatter(workspace.getCurrentContent());
    workspace.updateContent(envelope.frontmatter + (structured || newLanguage ? replaceTermLanguage(envelope.body, language, value) : value));
  }
  async function rewrite() {
    setBusy(true); setError("");
    try {
      if (!structured) throw new Error("原有解释请先通过完整编辑器明确归入语言区块，再进行单语重写。");
      const draft = await workspace.saveNow() ?? await workspace.ensureDraft();
      setProposal((await requestTermRewrite(draft.id, language, requirements)).proposal);
    } catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  async function adopt() {
    if (!proposal) return;
    setBusy(true); setError("");
    try { await workspace.applyProposalToDraft(proposal.id); setProposal(null); setRewriting(false); }
    catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  async function discardSuggestion() {
    if (!proposal) return;
    setBusy(true); setError("");
    try { await rejectProposal(proposal.id); setProposal(null); }
    catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  return <section className="term-language-card surface" aria-label="Term 解释">
    <div className="term-language-actions"><div role="group" aria-label="解释语言"><button disabled={busy} aria-pressed={language === "zh"} onClick={() => { setLanguage("zh"); setProposal(null); }}>中文</button><button disabled={busy} aria-pressed={language === "en"} onClick={() => { setLanguage("en"); setProposal(null); }}>English</button></div><button disabled={disabled || busy} onClick={() => setEditing(!editing)}>编辑</button><button disabled={disabled || busy} onClick={() => setRewriting(!rewriting)}>AI 重写</button></div>
    {!structured && <p className="subtle-copy">原有解释 · 保留原文，不推断语言 <button disabled={busy || disabled} onClick={() => { setNewLanguage(true); setEditing(true); }}>新增独立的{language === "zh" ? "中文" : "English"}解释</button></p>}
    {editing && <label className="field-label">Markdown 源码<textarea value={explanation} onChange={(event) => changeExplanation(event.target.value)} disabled={disabled || busy} rows={8} /></label>}
    {explanation ? <Markdown content={explanation} onNavigate={navigate} /> : <p>暂无{language === "en" ? " English" : "中文"}解释。可编辑补充，或显式请求 AI 生成。</p>}
    {structured && <details><summary>完整原文与其他内容</summary><Markdown content={body} onNavigate={navigate} /></details>}
    {rewriting && <div><label className="field-label">重写要求<textarea value={requirements} onChange={(event) => setRequirements(event.target.value)} /></label><p className="subtle-copy">点击后会将当前 Term Draft 发送给 DeepSeek；生成结果只供预览。</p><button disabled={disabled || busy || !requirements.trim()} onClick={() => void rewrite()}>{busy ? "正在生成…" : "生成当前语言建议"}</button></div>}
    {proposal && <section aria-label="重写对比"><p>原文 ↔ 新文</p><Markdown content={explanation} onNavigate={navigate} /><Markdown content={String((proposal.payload.result as Record<string, unknown>)?.explanation ?? "")} onNavigate={navigate} /><button disabled={busy} onClick={() => void adopt()}>采用到 Draft</button><button disabled={busy} onClick={() => void discardSuggestion()}>放弃</button></section>}
    {error && <p role="alert" className="error-copy">{error}</p>}
  </section>;
}
