import { readFrontmatterField } from "../metadataDraft.js";

export interface PaperSkillArtifact {
  type: "paperskill";
  variant: string;
  url: string;
  owner?: string;
}

export interface DraftCitation {
  source_id: string;
  locator: string | null;
  line: number;
  claim: string;
}

export function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function readPaperSkillArtifacts(value: unknown): PaperSkillArtifact[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const artifact = item as Record<string, unknown>;
    if (artifact.type !== "paperskill" || typeof artifact.variant !== "string" || typeof artifact.url !== "string") return [];
    return [{
      type: "paperskill" as const,
      variant: artifact.variant,
      url: artifact.url,
      ...(typeof artifact.owner === "string" ? { owner: artifact.owner } : {}),
    }];
  });
}

export function readSourcePdf(content: string): string {
  const attachments = readFrontmatterField(content, "source", "attachments");
  if (!attachments || typeof attachments !== "object") return "";
  const value = (attachments as Record<string, unknown>).local_pdf;
  return typeof value === "string" ? value : "";
}

export function readDraftCitations(content: string): DraftCitation[] {
  const citationPattern = /\[@([a-z0-9][a-z0-9-]*)(?:,\s*([^\]\n]+?))?\]/gi;
  return content.split("\n").flatMap((line, index) => {
    const matches = Array.from(line.matchAll(citationPattern));
    if (!matches.length) return [];
    const claim = line.replace(citationPattern, "").replace(/^\s*(?:[-*>]+\s*)?/, "").trim();
    return matches.map((match) => ({
      source_id: match[1],
      locator: match[2]?.trim() || null,
      line: index + 1,
      claim,
    }));
  });
}
