/**
 * The single door to the backend.
 *
 * Every failure that crosses it is an `ApiError` carrying the backend's own `detail`, so no
 * page has to guess at wording, and no page has to know the wire format.
 */

import type {
  CallDirection,
  CodeReply,
  CommitReply,
  DocumentDetail,
  DocumentListReply,
  HistoryReply,
  IndexOutcome,
  IndexRunReply,
  Neighbourhood,
  RepoListReply,
  RestoreReply,
  RevisionTextReply,
  SearchMode,
  SearchReply,
  StatusReply,
  TagCloudReply,
  TreeReply,
} from "./types";

/**
 * Where `/api` lives, relative to wherever index.html was served from.
 *
 * The build emits relative asset URLs and routing is hash-based, so the app has no idea at
 * build time whether it sits at the origin root or under a mount point. The directory the
 * document itself came from is the one thing that is true in both cases -- and with hash
 * routing it stays true, because navigation never touches the pathname.
 */
const API_ROOT = `${window.location.pathname.replace(/[^/]*$/, "")}api`;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Encode a knowledge-base path for use as URL path segments.
 *
 * Segment by segment: the slashes are structure the backend reads, everything else -- CJK
 * titles above all -- has to survive intact.
 */
export function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

function url(path: string, params?: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return `${API_ROOT}/${path}${query ? `?${query}` : ""}`;
}

async function refuse(response: Response): Promise<never> {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const raw = (body as { detail: unknown }).detail;
      detail = typeof raw === "string" ? raw : JSON.stringify(raw);
    }
  } catch {
    // A body that is not JSON tells us nothing the status line did not.
  }
  throw new ApiError(response.status, detail);
}

async function request<T>(target: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(target, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (failure) {
    throw new ApiError(0, `无法连接到服务：${(failure as Error).message}`);
  }
  if (!response.ok) return refuse(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function post<T>(target: string, body?: unknown): Promise<T> {
  return request<T>(target, { method: "POST", body: JSON.stringify(body ?? {}) });
}

export const api = {
  search(q: string, options: { limit?: number; mode?: SearchMode; repo?: string | null } = {}) {
    return request<SearchReply>(
      url("search", { q, limit: options.limit, mode: options.mode, repo: options.repo }),
    );
  },

  tree() {
    return request<TreeReply>(url("tree"));
  },

  tags() {
    return request<TagCloudReply>(url("tags"));
  },

  documents(tag?: string | null) {
    return request<DocumentListReply>(url("documents", { tag }));
  },

  document(path: string) {
    return request<DocumentDetail>(url(`documents/${encodePath(path)}`));
  },

  links(path: string, depth = 1) {
    return request<Neighbourhood>(url(`documents/${encodePath(path)}/links`, { depth }));
  },

  writeDocument(path: string, text: string, author: string) {
    return request<DocumentDetail>(url(`documents/${encodePath(path)}`), {
      method: "PUT",
      body: JSON.stringify({ text, author }),
    });
  },

  deleteDocument(path: string, author: string) {
    return request<void>(url(`documents/${encodePath(path)}`, { author }), { method: "DELETE" });
  },

  history(path?: string | null, limit = 50) {
    return request<HistoryReply>(url("history", { path, limit }));
  },

  commit(revision: string) {
    return request<CommitReply>(url(`history/${encodeURIComponent(revision)}`));
  },

  revisionText(revision: string, path: string) {
    return request<RevisionTextReply>(
      url(`history/${encodeURIComponent(revision)}/document`, { path }),
    );
  },

  restore(revision: string, path: string, author: string) {
    return post<RestoreReply>(url(`history/${encodeURIComponent(revision)}/restore`), {
      path,
      author,
    });
  },

  repos() {
    return request<RepoListReply>(url("code/repos"));
  },

  architecture(name: string) {
    return request<CodeReply>(url(`code/repos/${encodeURIComponent(name)}/architecture`));
  },

  indexRepo(name: string) {
    return post<IndexOutcome>(url(`code/repos/${encodeURIComponent(name)}/index`));
  },

  searchCode(q: string, mode: SearchMode = "symbol", repo?: string | null) {
    return request<CodeReply>(url("code/search", { q, mode, repo }));
  },

  symbol(name: string, repo?: string | null) {
    return request<CodeReply>(url("code/symbol", { name, repo }));
  },

  calls(symbol: string, direction: CallDirection = "inbound", depth = 3, repo?: string | null) {
    return request<CodeReply>(url("code/calls", { symbol, direction, depth, repo }));
  },

  cypher(cypher: string, repo?: string | null) {
    return post<CodeReply>(url("code/query"), { cypher, repo: repo || null });
  },

  status() {
    return request<StatusReply>(url("system/status"));
  },

  reindexDocuments() {
    return post<{ indexed: number }>(url("system/reindex/documents"));
  },

  reindexCode(repo: string | null) {
    return post<IndexRunReply>(url("system/reindex/code"), { repo });
  },
};
