import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  recordSearchClick,
  type EntityType,
} from "./api";
import { LoadingState } from "./ui";

const HomePage = lazy(() => import("./Pages").then((module) => ({ default: module.HomePage })));
const SearchPage = lazy(() => import("./Pages").then((module) => ({ default: module.SearchPage })));
const LibraryPage = lazy(() => import("./Pages").then((module) => ({ default: module.LibraryPage })));
const TermsPage = lazy(() => import("./Pages").then((module) => ({ default: module.TermsPage })));
const TopicsPage = lazy(() => import("./Pages").then((module) => ({ default: module.TopicsPage })));
const ReviewPage = lazy(() => import("./Pages").then((module) => ({ default: module.ReviewPage })));
const ExplorerPage = lazy(() => import("./Explorer").then((module) => ({ default: module.ExplorerPage })));
const WorkspacePage = lazy(() => import("./Workspace").then((module) => ({ default: module.WorkspacePage })));
const NewNotePage = lazy(() => import("./workspace/NewNotePage").then((module) => ({ default: module.NewNotePage })));

interface LocationState {
  pathname: string;
  search: string;
  hash: string;
}

const navigation = [
  { route: "/", title: "Home", translation: "首页", icon: "⌂" },
  { route: "/search", title: "Search", translation: "搜索", icon: "⌕" },
  { route: "/library", title: "Library", translation: "资料库", icon: "▤" },
  { route: "/terms", title: "Terms", translation: "术语", icon: "Aa" },
  { route: "/topics", title: "Topics", translation: "主题", icon: "✳" },
  { route: "/review", title: "Review", translation: "审阅", icon: "✓" },
  { route: "/explorer", title: "Explorer", translation: "知识探索", icon: "⌘" },
];

function currentLocation(): LocationState {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

export default function App() {
  const [location, setLocation] = useState<LocationState>(() => currentLocation());
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [quickSearch, setQuickSearch] = useState("");
  const [sidebarPinned, setSidebarPinned] = useState(() => {
    try {
      return window.localStorage.getItem("knowledgebase.sidebar-pinned") === "true";
    } catch {
      return false;
    }
  });
  const [sidebarPeek, setSidebarPeek] = useState(false);
  const [finePointer, setFinePointer] = useState(false);
  const sidebarHoverTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const update = () => setLocation(currentLocation());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(hover: hover) and (pointer: fine)");
    const update = () => setFinePointer(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem("knowledgebase.sidebar-pinned", String(sidebarPinned));
    } catch {
      // Local storage can be unavailable in private browsing contexts.
    }
  }, [sidebarPinned]);

  const navigate = useCallback((path: string) => {
    window.history.pushState({}, "", path);
    setLocation(currentLocation());
    setMobileNavOpen(false);
    setSidebarPeek(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const route = useMemo(() => resolveRoute(location.pathname), [location.pathname]);
  const contentWorkspace = route.kind === "reader" || route.kind === "new-note";
  useEffect(() => {
    setSidebarPeek(false);
    if (sidebarHoverTimerRef.current !== null) {
      window.clearTimeout(sidebarHoverTimerRef.current);
      sidebarHoverTimerRef.current = null;
    }
  }, [location.pathname]);
  useEffect(() => () => {
    if (sidebarHoverTimerRef.current !== null) window.clearTimeout(sidebarHoverTimerRef.current);
  }, []);

  function handleSidebarPointerEnter() {
    if (!contentWorkspace || !finePointer || sidebarPinned || sidebarPeek) return;
    if (sidebarHoverTimerRef.current !== null) window.clearTimeout(sidebarHoverTimerRef.current);
    sidebarHoverTimerRef.current = window.setTimeout(() => {
      setSidebarPeek(true);
      sidebarHoverTimerRef.current = null;
    }, 100);
  }

  function handleSidebarPointerLeave() {
    if (!contentWorkspace || !finePointer || sidebarPinned) return;
    if (sidebarHoverTimerRef.current !== null) window.clearTimeout(sidebarHoverTimerRef.current);
    sidebarHoverTimerRef.current = window.setTimeout(() => {
      setSidebarPeek(false);
      sidebarHoverTimerRef.current = null;
    }, 300);
  }

  function toggleSidebarPin() {
    const nextPinned = !sidebarPinned;
    setSidebarPinned(nextPinned);
    setSidebarPeek(!nextPinned);
  }
  const activeNav = route.kind === "reader"
    ? route.entityType === "term" ? "/terms" : "/library"
    : navigation.find((item) => item.route === route.path)?.route ?? "/";
  const pageTitle = route.kind === "reader"
    ? route.entityType === "document" ? "Document" : route.entityType === "term" ? "Term" : "Source"
    : route.kind === "new-note" ? "New Note" : navigation.find((item) => item.route === activeNav)?.title ?? "Home";

  const openEntity = useCallback((
    type: EntityType,
    id: string,
    clickedFromSearch = false,
    collectionId?: string,
  ) => {
    if (clickedFromSearch && type === "document") void recordSearchClick(id).catch(() => undefined);
    const prefix = type === "document" ? "documents" : type === "term" ? "terms" : "sources";
    const context = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
    navigate(`/${prefix}/${encodeURIComponent(id)}${context}`);
  }, [navigate]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = quickSearch.trim();
    navigate(query ? `/search?q=${encodeURIComponent(query)}` : "/search");
  };

  let page: ReactNode;
  if (route.kind === "new-note") {
    page = <Suspense fallback={<LoadingState />}><NewNotePage navigate={navigate} /></Suspense>;
  } else if (route.kind === "reader") {
    const query = new URLSearchParams(location.search);
    const collectionId = query.get("collection") ?? undefined;
    const batchCollectionId = query.get("publishAll") === "1" ? collectionId : undefined;
    page = <Suspense fallback={<LoadingState />}><WorkspacePage key={`${route.entityType}:${route.id}`} type={route.entityType} id={route.id} navigate={navigate} collectionId={collectionId} batchCollectionId={batchCollectionId} /></Suspense>;
  } else if (route.path === "/search") {
    const query = new URLSearchParams(location.search).get("q") ?? "";
    page = <Suspense fallback={<LoadingState />}><SearchPage key={`${location.pathname}${location.search}`} initialQuery={query} onOpen={openEntity} /></Suspense>;
  } else if (route.path === "/library") {
    page = <Suspense fallback={<LoadingState />}><LibraryPage onOpen={openEntity} /></Suspense>;
  } else if (route.path === "/terms") {
    page = <Suspense fallback={<LoadingState />}><TermsPage onOpen={openEntity} /></Suspense>;
  } else if (route.path === "/topics") {
    page = <Suspense fallback={<LoadingState />}><TopicsPage onOpen={openEntity} /></Suspense>;
  } else if (route.path === "/review") {
    page = <Suspense fallback={<LoadingState />}><ReviewPage onOpen={openEntity} navigate={navigate} /></Suspense>;
  } else if (route.path === "/explorer") {
    page = <Suspense fallback={<LoadingState />}><ExplorerPage onOpen={openEntity} navigate={navigate} /></Suspense>;
  } else {
    page = <Suspense fallback={<LoadingState />}><HomePage onOpen={openEntity} navigate={navigate} /></Suspense>;
  }

  return (
    <div className={`app-frame ${contentWorkspace ? "content-workspace" : ""} ${sidebarPinned ? "sidebar-pinned" : ""} ${sidebarPeek ? "sidebar-peek" : ""}`}>
      <aside
        className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}
        onPointerEnter={handleSidebarPointerEnter}
        onPointerLeave={handleSidebarPointerLeave}
        onFocus={() => { if (contentWorkspace && finePointer && !sidebarPinned) setSidebarPeek(true); }}
        onBlur={(event) => {
          if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
          handleSidebarPointerLeave();
        }}
      >
        {contentWorkspace && <button className="sidebar-rail-toggle" aria-label={sidebarPeek ? "收起导航" : "展开导航"} aria-expanded={sidebarPinned || sidebarPeek} onClick={() => setSidebarPeek((open) => !open)}>{sidebarPeek ? "‹" : "›"}</button>}
        <button className="brand" onClick={() => navigate("/")} aria-label="KnowledgeBase 首页">
          <span className="brand-mark">K</span>
          <span className="brand-copy"><strong>KnowledgeBase</strong><small>REFERENCE HUB</small></span>
        </button>

        <div className="sidebar-caption">工作区</div>
        <nav className="main-navigation" aria-label="主导航">
          {navigation.map((item) => (
            <button
              key={item.route}
              className={`nav-item ${activeNav === item.route ? "nav-active" : ""}`}
              aria-current={activeNav === item.route ? "page" : undefined}
              onClick={() => navigate(item.route)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-copy"><strong>{item.title}</strong><small>{item.translation}</small></span>
              {activeNav === item.route && <span className="nav-current-mark" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          {contentWorkspace && <button className="sidebar-pin-button" aria-pressed={sidebarPinned} onClick={toggleSidebarPin}>{sidebarPinned ? "取消固定侧栏" : "固定侧栏"}</button>}
          <div className="privacy-badge"><span className="privacy-icon">◈</span><span><strong>本地知识库</strong><small>Canonical · Markdown + YAML</small></span></div>
          <div className="sidebar-version"><span className="connection-dot" /> Private workspace <span>v1</span></div>
        </div>
      </aside>

      {mobileNavOpen && <button className="mobile-scrim" onClick={() => setMobileNavOpen(false)} aria-label="关闭导航" />}

      <main className="main-column">
        <header className="top-header">
          <div className="top-header-title"><button className="mobile-menu-button" onClick={() => setMobileNavOpen((open) => !open)} aria-label="切换导航">☰</button><span>{pageTitle}</span></div>
          <form className="global-search" onSubmit={submitSearch}>
            <span className="global-search-icon">⌕</span>
            <input value={quickSearch} onChange={(event) => setQuickSearch(event.target.value)} placeholder="快速搜索知识库" aria-label="快速搜索知识库" />
            <kbd>Enter</kbd>
          </form>
          <div className="top-header-end"><span className="top-status-dot" /><span>私有工作区</span><button className="avatar-button" title="KnowledgeBase">KB</button></div>
        </header>
        <div className="page-container" key={route.kind === "reader" ? "reader-workspace" : `${route.kind}:${route.path}:${location.search}`}>
          {page}
        </div>
        <footer className="main-footer"><span>KnowledgeBase</span><span>Canonical knowledge stays in Markdown and YAML.</span></footer>
      </main>
    </div>
  );
}

function resolveRoute(pathname: string):
  | { kind: "page"; path: string }
  | { kind: "reader"; entityType: EntityType; id: string; path: string }
  | { kind: "new-note"; path: string } {
  const parts = pathname.split("/").filter(Boolean).map((part) => decodeURIComponent(part));
  if (!parts.length) return { kind: "page", path: "/" };
  if (parts[0] === "new-note") return { kind: "new-note", path: "/" };
  if (parts[0] === "documents" && parts[1]) return { kind: "reader", entityType: "document", id: parts[1], path: "/library" };
  if (parts[0] === "terms" && parts[1]) return { kind: "reader", entityType: "term", id: parts[1], path: "/terms" };
  if (parts[0] === "sources" && parts[1]) return { kind: "reader", entityType: "source", id: parts[1], path: "/library" };
  const route = `/${parts[0]}`;
  return navigation.some((item) => item.route === route) ? { kind: "page", path: route } : { kind: "page", path: "/" };
}
