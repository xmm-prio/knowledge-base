/** The REST contract, transcribed from `src/knowledge_base/api/`. */

export interface DocumentSummary {
  path: string;
  title: string;
  summary: string;
  tags: string[];
}

export interface Observation {
  category: string;
  content: string;
  tags: string[];
}

export interface DocumentDetail extends DocumentSummary {
  /** Raw Markdown, byte-for-byte as it sits on disk. */
  text: string;
  observations: Observation[];
  /** Null while the write is still inside the 30s quiet period before its commit. */
  created_at: string | null;
  updated_at: string | null;
}

export interface TreeNode {
  name: string;
  path: string;
  directories: TreeNode[];
  documents: DocumentSummary[];
}

export interface TreeReply {
  directories: TreeNode[];
}

export interface DocumentListReply {
  documents: DocumentSummary[];
}

export interface Tag {
  tag: string;
  count: number;
}

export interface TagCloudReply {
  tags: Tag[];
}

export interface LinkedDocument {
  path: string;
  title: string;
}

export interface Link {
  type: string;
  source: string;
  /** Empty while the target document has not been written yet. */
  target: string;
  target_name: string;
}

export interface Neighbourhood {
  origin: string;
  documents: LinkedDocument[];
  links: Link[];
}

export type HitKind = "document" | "observation";

export interface Hit {
  kind: HitKind | string;
  path: string;
  title: string;
  summary: string;
  snippet: string;
  /** BM25: lower is better. Never render it as a percentage. */
  score: number;
}

/** The code domain's envelope. `payload` is the upstream binary's JSON, shape unconfirmed. */
export interface CodeReply {
  ok: boolean;
  payload: unknown;
  caveat: string | null;
  error: string | null;
}

export interface SearchReply {
  query: string;
  documents: { hits: Hit[] };
  code: CodeReply;
}

export interface Repo {
  name: string;
  path: string;
  indexed: boolean;
}

export interface RepoListReply {
  repos: Repo[];
}

export interface IndexOutcome {
  repo: string;
  ok: boolean;
  payload: unknown;
}

export interface IndexRunReply {
  outcomes: IndexOutcome[];
}

export interface Revision {
  revision: string;
  author: string;
  message: string;
  at: string;
}

export interface HistoryReply {
  path: string | null;
  revisions: Revision[];
}

export interface CommitReply {
  revision: string;
  paths: string[];
}

export interface RevisionTextReply {
  path: string;
  revision: string;
  text: string;
}

export interface RestoreReply {
  path: string;
  restored_from: string;
  /** Null when the document already held that text, so no commit was made. */
  revision: string | null;
}

export interface DocumentsStatus {
  ok: boolean;
  documents: number;
  observations: number;
  tags: number;
  error: string | null;
}

export interface CodeStatus {
  /** Null means the upstream's health is unknown, which is not the same as healthy. */
  ok: boolean | null;
  repos: number;
  indexed: number;
  error: string | null;
}

export interface McpStatus {
  url: string;
  opencode_config: string;
}

export interface StatusReply {
  documents: DocumentsStatus;
  code: CodeStatus;
  mcp: McpStatus;
}

export type SearchMode = "symbol" | "text";
export type CallDirection = "inbound" | "outbound" | "both";
