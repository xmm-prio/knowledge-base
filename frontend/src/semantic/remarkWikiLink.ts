/**
 * `[[Target]]` in prose becomes a link, or a visibly dead one.
 *
 * WikiLinks are not CommonMark, so remark leaves them as literal text. This walks the text
 * nodes and swaps each occurrence for a node of its own -- resolved targets get an href into
 * the documents route, unresolved ones render as a greyed span, because a relation to a
 * document nobody has written yet is a normal state of a growing knowledge base, not an
 * error. Nothing here emits raw HTML, so the pipeline stays free of rehype-raw.
 */

import type { Emphasis, Link, Root, Text } from "mdast";
import { visit } from "unist-util-visit";
import { WIKILINK } from "./syntax";

export interface WikiLinkOptions {
  /** Target name to knowledge-base path, as the links endpoint resolved them. */
  resolve: (name: string) => string | null;
  /** Where a resolved target should point. */
  href: (path: string) => string;
}

export function remarkWikiLink(options: WikiLinkOptions) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (!parent || index === null || index === undefined) return;
      if (parent.type === "link" || parent.type === "linkReference") return;
      if (!node.value.includes("[[")) return;

      const replacement = split(node.value, options);
      if (!replacement) return;
      parent.children.splice(index, 1, ...(replacement as never[]));
      return index + replacement.length;
    });
  };
}

type Piece = Text | Link | Emphasis;

function split(value: string, options: WikiLinkOptions): Piece[] | null {
  const pieces: Piece[] = [];
  let cursor = 0;
  WIKILINK.lastIndex = 0;

  for (let match = WIKILINK.exec(value); match; match = WIKILINK.exec(value)) {
    if (match.index > cursor) {
      pieces.push({ type: "text", value: value.slice(cursor, match.index) });
    }
    pieces.push(node(match[1], options));
    cursor = match.index + match[0].length;
  }
  if (!pieces.length) return null;
  if (cursor < value.length) pieces.push({ type: "text", value: value.slice(cursor) });
  return pieces;
}

function node(name: string, options: WikiLinkOptions): Link | Emphasis {
  const path = options.resolve(name);
  const children: Text[] = [{ type: "text", value: name }];
  if (!path) {
    // Not a link node: a link would carry an empty `href` onto the span it renders as.
    return {
      type: "emphasis",
      children,
      data: {
        hName: "span",
        hProperties: { className: ["wikilink", "wikilink-missing"], title: "尚未创建" },
      },
    };
  }
  return {
    type: "link",
    url: options.href(path),
    children,
    data: { hProperties: { className: ["wikilink"] } },
  };
}
