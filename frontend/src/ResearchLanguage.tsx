export type ResearchLanguage = "zh" | "en";

export function ResearchLanguageToggle({
  language,
  onChange,
}: {
  language: ResearchLanguage;
  onChange: (language: ResearchLanguage) => void;
}) {
  return <div className="research-language-switch" role="group" aria-label="Candidate language">
    <button type="button" aria-pressed={language === "en"} onClick={() => onChange("en")}>EN</button>
    <button type="button" aria-pressed={language === "zh"} onClick={() => onChange("zh")}>中文</button>
  </div>;
}
