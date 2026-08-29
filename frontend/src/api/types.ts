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

/**
 * Which of the four failures a code answer hit. The distinction decides who is being asked to
 * do something: fix the search box, ask a different question, or go and find an operator.
 */
export type FailureKind = "bad_request" | "refused" | "unavailable" | "internal";

/** One symbol, under the name to read and the name to ask with. Never confuse the two. */
export interface CodeSymbol {
  canonical_qn: string;
  display_qn: string;
  repo: string | null;
  file: string | null;
  line: number | null;
  kind: string | null;
}

export interface SymbolMatches {
  matches: CodeSymbol[];
  /** Entries the upstream returned that carry no name this service could identify. */
  unreadable: number;
  /** The upstream's own payload, present only when nothing at all could be read from it. */
  raw: unknown;
}

export interface CallNode {
  symbol: CodeSymbol;
  depth: number;
}

export interface CallEdge {
  caller: string;
  callee: string;
}

export interface CallChain {
  root: string;
  direction: string;
  nodes: CallNode[];
  edges: CallEdge[];
  /** Relations that could not be pinned to one symbol at each end, dropped and counted. */
  unresolved: number;
  raw: unknown;
}

/**
 * The code domain's envelope. `payload` is this service's own reading of the answer where it
 * had one -- `SymbolMatches`, `CallChain` -- and the upstream's JSON verbatim where it did not.
 */
export interface CodeReply {
  ok: boolean;
  payload: unknown;
  caveat: string | null;
  error: string | null;
  kind: FailureKind | null;
  /** The identifier this failure was logged under. Quotable to an operator. */
  diagnostic: string | null;
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
  /** Empty when the service has no address worth handing out; `error` says why. */
  url: string;
  opencode_config: string;
  error: string | null;
}

export interface StatusReply {
  documents: DocumentsStatus;
  code: CodeStatus;
  mcp: McpStatus;
}

export type SearchMode = "symbol" | "text" | "regex";
export type CallDirection = "inbound" | "outbound" | "both";
