/** Every in-app link is built here, so a route rename is one edit. */

/**
 * Segment by segment, like the API client does: the slashes are route structure, the CJK
 * titles between them are not. React Router decodes each segment back on the way in, so
 * nothing downstream decodes a second time.
 */
function encodeSegments(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export const routes = {
  search: (q?: string) => (q ? `/search?q=${encodeURIComponent(q)}` : "/search"),
  documents: (path?: string) => (path ? `/documents/${encodeSegments(path)}` : "/documents"),
  tags: (tag?: string) => (tag ? `/tags?tag=${encodeURIComponent(tag)}` : "/tags"),
  history: (path?: string) => (path ? `/history?path=${encodeURIComponent(path)}` : "/history"),
  code: () => "/code",
  system: () => "/system",
};
