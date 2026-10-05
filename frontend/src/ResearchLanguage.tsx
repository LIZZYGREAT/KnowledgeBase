import { useCallback, useEffect, useState } from "react";

export type ResearchLanguage = "zh" | "en";

const STORAGE_KEY = "knowledgebase.research-language";
const CHANGE_EVENT = "knowledgebase:research-language-change";

function readResearchLanguage(): ResearchLanguage {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

export function useResearchLanguage(): [ResearchLanguage, (language: ResearchLanguage) => void] {
  const [language, setLanguageState] = useState<ResearchLanguage>(readResearchLanguage);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setLanguageState(event.newValue === "en" ? "en" : "zh");
    };
    const onChange = (event: Event) => {
      const value = (event as CustomEvent<ResearchLanguage>).detail;
      if (value === "zh" || value === "en") setLanguageState(value);
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, onChange);
    };
  }, []);

  const setLanguage = useCallback((nextLanguage: ResearchLanguage) => {
    setLanguageState(nextLanguage);
    try {
      window.localStorage.setItem(STORAGE_KEY, nextLanguage);
    } catch {
      // The in-memory toggle still works when browser storage is unavailable.
    }
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: nextLanguage }));
  }, []);

  return [language, setLanguage];
}

export function ResearchLanguageToggle() {
  const [language, setLanguage] = useResearchLanguage();
  return <div className="research-language-switch" role="group" aria-label="候选语言">
    <button type="button" aria-pressed={language === "zh"} onClick={() => setLanguage("zh")}>中文</button>
    <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
  </div>;
}
