const sections = ["知识模型", "搜索与索引", "审阅优先的导入"];

export default function App() {
  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="KnowledgeBase 首页">
          <span className="brand-mark">K</span>
          <span>KnowledgeBase</span>
        </a>
        <span className="phase-pill">后端阶段 · 0–8</span>
      </header>

      <section className="welcome" aria-labelledby="welcome-title">
        <p className="eyebrow">REFERENCE HUB</p>
        <h1 id="welcome-title">让知识保持清晰、可查、可维护。</h1>
        <p className="intro">
          Knowledge API 已就绪。Reference Hub 阅读与编辑界面仍待接入。
        </p>
      </section>

      <section className="progress" aria-label="当前实现范围">
        {sections.map((section, index) => (
          <article className="progress-card" key={section}>
            <span className="step">0{index + 1}</span>
            <h2>{section}</h2>
            <p>{index === 0 ? "以 Markdown 和 YAML 保存规范知识" : index === 1 ? "结构化筛选、别名与中文检索" : "Markdown 和 PDF 暂存及人工审阅"}</p>
          </article>
        ))}
      </section>

      <footer>Canonical knowledge stays in Markdown and YAML.</footer>
    </main>
  );
}
