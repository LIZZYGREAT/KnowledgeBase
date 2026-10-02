import { parseDocument } from "yaml";

export function readFrontmatterField(content, type, key) {
  try {
    let yamlText = content;
    if (type !== "source") {
      const match = /^(---\r?\n)([\s\S]*?)(\r?\n---)([\s\S]*)$/.exec(content);
      if (!match) return undefined;
      yamlText = match[2];
    }
    const document = parseDocument(yamlText);
    if (document.errors.length) return undefined;
    return document.get(key);
  } catch {
    return undefined;
  }
}

export function patchYamlField(content, type, key, value) {
  let yamlText = content;
  let open = "";
  let separator = "";
  let suffix = "";
  if (type !== "source") {
    const match = /^(---\r?\n)([\s\S]*?)(\r?\n---)([\s\S]*)$/.exec(content);
    if (!match) throw new Error("缺少有效 frontmatter；请先修复 Markdown 元数据。");
    [open, yamlText, separator, suffix] = [match[1], match[2], match[3], match[4]];
  }
  const document = parseDocument(yamlText);
  if (document.errors.length) throw new Error("YAML frontmatter 无法解析，请先修复语法。");
  document.set(key, value);
  const serialized = document.toString().trimEnd();
  return type === "source" ? `${serialized}\n` : `${open}${serialized}${separator}${suffix}`;
}
