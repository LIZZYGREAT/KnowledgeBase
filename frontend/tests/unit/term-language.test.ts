import { describe, expect, it } from "vitest";
import { renumberTermH3Headings, replaceTermLanguage, termLanguageSections } from "../../src/termLanguage";

describe("Term language sections", () => {
  it("ignores headings in fences and preserves the other language", () => {
    const body = "# EWC\n\n## 一、中文解释\n\nFisher Information。\n\n```markdown\n## 二、English Explanation\n```\n\n## 二、English Explanation\n\nEnglish body.\n";
    expect(termLanguageSections(body).en?.content).toBe("English body.");
    const changed = replaceTermLanguage(body, "zh", "新解释");
    expect(termLanguageSections(changed).en?.content).toBe("English body.");
    expect(termLanguageSections(changed).zh?.content).toBe("新解释");
  });
  it("retains original content and represents missing languages explicitly", () => {
    const body = "# EWC\n\nOriginal unstructured body.\n";
    expect(termLanguageSections(body)).toEqual({});
    const changed = replaceTermLanguage(body, "en", "English body.");
    expect(changed).toContain(body.trim());
    expect(termLanguageSections(changed).zh).toBeUndefined();
  });

  it("renumbers only real H3 headings and restarts numbering at each language section", () => {
    const body = "# EWC\n\n## 一、中文解释\n\n### Definition\n\nChinese body.\n\n### 8. Example\n\nAnother body.\n\n```markdown\n### Example in code\n```\n\n## 二、English Explanation\n\n### Meaning\n\nEnglish body.\n";

    const result = renumberTermH3Headings(body);

    expect(result.correctedCount).toBe(3);
    expect(result.content).toContain("### 1. Definition");
    expect(result.content).toContain("### 2. Example");
    expect(result.content).toContain("```markdown\n### Example in code\n```");
    expect(result.content).toContain("## 二、English Explanation\n\n### 1. Meaning");
    expect(result.content).toContain("Chinese body.");
    expect(result.content).toContain("English body.");
  });
});
