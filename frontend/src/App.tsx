const sections = ["知识模型", "Markdown 解析", "确定性校验"];

export default function App() {
  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="KnowledgeBase 首页">
          <span className="brand-mark">K</span>
          <span>KnowledgeBase</span>
        </a>
        <span className="phase-pill">基础阶段</span>
      </header>

      <section className="welcome" aria-labelledby="welcome-title">
        <p className="eyebrow">REFERENCE HUB · FOUNDATION</p>
        <h1 id="welcome-title">让知识保持清晰、可查、可维护。</h1>
        <p className="intro">
          KnowledgeBase 正在建立 Markdown 知识模型与确定性校验基础。
          阅读、搜索和编辑界面将在后续阶段接入。
        </p>
      </section>

      <section className="progress" aria-label="当前实现范围">
        {sections.map((section, index) => (
          <article className="progress-card" key={section}>
            <span className="step">0{index + 1}</span>
            <h2>{section}</h2>
            <p>{index === 0 ? "文档、术语、来源与分类" : index === 1 ? "Frontmatter、Wiki Link、Citation 与数学片段" : "标题层级、公式边界与 Mermaid 声明"}</p>
          </article>
        ))}
      </section>

      <footer>Canonical knowledge stays in Markdown and YAML.</footer>
    </main>
  );
}
