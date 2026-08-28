/**
 * Routing.
 *
 * Hash-based on purpose: the build emits relative asset URLs because the backend mounts
 * dist/ with StaticFiles, and a hash route works the same whether that mount lands at the
 * origin root or under a prefix -- there is no base path to keep in step with the server.
 */

import { lazy } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./Shell";

// Split per route: CodeMirror and the remark pipeline are most of the bundle and only two
// routes need them, so nobody pays for the editor to look at the tag cloud.
const SearchPage = lazy(() => import("../pages/SearchPage").then((m) => ({ default: m.SearchPage })));
const DocumentsPage = lazy(() =>
  import("../pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage })),
);
const TagsPage = lazy(() => import("../pages/TagsPage").then((m) => ({ default: m.TagsPage })));
const HistoryPage = lazy(() =>
  import("../pages/HistoryPage").then((m) => ({ default: m.HistoryPage })),
);
const CodePage = lazy(() => import("../pages/CodePage").then((m) => ({ default: m.CodePage })));
const SystemPage = lazy(() => import("../pages/SystemPage").then((m) => ({ default: m.SystemPage })));

export function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/*" element={<DocumentsPage />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/code" element={<CodePage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="*" element={<Navigate to="/search" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
