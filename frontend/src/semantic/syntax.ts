/**
 * Semantic Markdown, recognized exactly the way the backend recognizes it.
 *
 * The regexes here are transcribed from `knowledge_base/docs/notes.py`. Both the renderer and
 * the editor's highlighter read them from this one module, so the page can never disagree
 * with itself about what counts as an observation -- or, worse, with the index.
 *
 * Nothing here ever rewrites text. The editor is a source editor (ADR-0005): a document's
 * bytes are the truth, and this module only ever reads them.
 */

/** `- [category] content #tag`. The category may hold no brackets or parens -- upstream's rule. */
const OBSERVATION_LINE = /^- \[([^[\]()]+)\]\s+(.+)$/;

/** `- relation_type [[Target]]`. */
const RELATION_LINE = /^- (\S+) \[\[(.+?)\]\]\s*$/;

/** Upstream reads a trailing `(...)` as context, so writers append this to absorb the rule. */
const PAREN_GUARD = "()";

export const OBSERVATIONS_HEADING = "## Observations";
export const RELATIONS_HEADING = "## Relations";

export const WIKILINK = /\[\[([^[\]]+)\]\]/g;

export interface ParsedObservation {
  category: string;
  content: string;
  tags: string[];
}

export interface ParsedRelation {
  type: string;
  target: string;
}

export function parseObservation(line: string): ParsedObservation | null {
  const match = OBSERVATION_LINE.exec(line);
  if (!match) return null;

  let rest = match[2];
  if (rest.endsWith(PAREN_GUARD) && rest !== PAREN_GUARD) {
    rest = rest.slice(0, -PAREN_GUARD.length).trimEnd();
  }

  const words = rest.split(" ");
  const tags: string[] = [];
  while (words.length > 1 && words[words.length - 1].startsWith("#")) {
    tags.unshift(words.pop()!.slice(1));
  }

  return { category: match[1].trim(), content: words.join(" "), tags };
}

export function parseRelation(line: string): ParsedRelation | null {
  const match = RELATION_LINE.exec(line);
  return match ? { type: match[1], target: match[2] } : null;
}

export type Segment =
  | { kind: "markdown"; text: string }
  | { kind: "observations"; items: ParsedObservation[] }
  | { kind: "relations"; items: ParsedRelation[] };

/**
 * Split a document body into prose and the two kinds of semantic line.
 *
 * Line-based rather than mdast-based on purpose. `[category]` is a valid CommonMark shortcut
 * reference and `[[target]]` is not CommonMark at all, so any parser-level recognition would
 * disagree with the indexer at the edges. Splitting on the same regex the indexer uses means
 * what the reader sees highlighted is exactly what got indexed.
 */
export function segment(body: string): Segment[] {
  const segments: Segment[] = [];
  let prose: string[] = [];

  const flush = () => {
    const text = prose.join("\n");
    if (text.trim()) segments.push({ kind: "markdown", text });
    prose = [];
  };

  const append = <T,>(kind: "observations" | "relations", item: T) => {
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) {
      (last.items as T[]).push(item);
      return;
    }
    segments.push({ kind, items: [item] } as Segment);
  };

  for (const raw of body.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (line === OBSERVATIONS_HEADING || line === RELATIONS_HEADING) continue;

    const observation = parseObservation(line);
    if (observation) {
      flush();
      append("observations", observation);
      continue;
    }
    const relation = parseRelation(line);
    if (relation) {
      flush();
      append("relations", relation);
      continue;
    }
    prose.push(raw);
  }
  flush();
  return segments;
}

const FRONTMATTER = /^---\r?\n[\s\S]*?\r?\n---[ \t]*\r?\n?/;

/** Frontmatter is already shown as the document's title, summary and tags; drop it from prose. */
export function stripFrontmatter(text: string): string {
  return text.replace(FRONTMATTER, "");
}

/**
 * Where a WikiLink target resolves to, given the paths that exist.
 *
 * Targets are written as bare names, not paths. `links` already resolved them for the
 * document being read; for anything it did not resolve, the link is dead on purpose and the
 * page says so rather than pretending.
 */
export function resolveWikiLink(name: string, resolved: Map<string, string>): string | null {
  return resolved.get(name) ?? null;
}
