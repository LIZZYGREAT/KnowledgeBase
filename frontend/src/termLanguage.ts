import { parseMarkdownBlocks } from "./markdownBlocks";

export type TermLanguage = "zh" | "en";
const labels: Record<TermLanguage, string> = { zh: "中文解释", en: "English Explanation" };

export function termLanguageSections(body: string) {
  const headings = parseMarkdownBlocks(body).blocks.filter((block) => block.type === "heading" && /^##\s/.test(block.raw));
  const sections: Partial<Record<TermLanguage, { start: number; end: number; content: string }>> = {};
  headings.forEach((heading, index) => {
    const label = heading.raw.replace(/^##\s+[一二三四五六七八九十]+、\s*/, "").trim();
    const language = (Object.keys(labels) as TermLanguage[]).find((key) => labels[key] === label);
    if (!language) return;
    const end = headings[index + 1]?.start ?? body.length;
    sections[language] = { start: heading.end, end, content: body.slice(heading.end, end).trim() };
  });
  return sections;
}

export function replaceTermLanguage(body: string, language: TermLanguage, explanation: string) {
  const section = termLanguageSections(body)[language];
  if (section) return body.slice(0, section.start) + "\n\n" + explanation.trim() + "\n\n" + body.slice(section.end);
  const count = parseMarkdownBlocks(body).blocks.filter((block) => block.type === "heading" && /^##\s/.test(block.raw)).length;
  const numeral = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][count];
  if (!numeral) throw new Error("请在完整 Markdown 编辑器中新增语言区块。");
  return body.trimEnd() + `\n\n## ${numeral}、${labels[language]}\n\n${explanation.trim()}\n`;
}
