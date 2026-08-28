/**
 * Semantic Markdown highlighting for the source editor.
 *
 * A decoration layer only: it adds marks over ranges of the document and never touches a
 * character of it. That is the whole point of ADR-0005 -- the file's bytes are the truth, and
 * an editor that re-serializes would turn `- [pitfall]` into `- \[pitfall]` and quietly
 * rewrite the corpus. Highlighting is how the reader gets structure back without paying for
 * it in bytes.
 */

import { RangeSetBuilder } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";

const OBSERVATION_LINE = /^- \[([^[\]()]+)\]\s+(.+)$/;
const RELATION_LINE = /^- (\S+) \[\[(.+?)\]\]\s*$/;
const TRAILING_TAG = /\s(#[^\s#]+)/g;
const WIKILINK = /\[\[([^[\]]+)\]\]/g;

const observationLine = Decoration.line({ class: "cm-observation-line" });
const relationLine = Decoration.line({ class: "cm-relation-line" });
const category = Decoration.mark({ class: "cm-observation-category" });
const tag = Decoration.mark({ class: "cm-observation-tag" });
const wikilink = Decoration.mark({ class: "cm-wikilink" });
const relationType = Decoration.mark({ class: "cm-relation-type" });

interface Marked {
  from: number;
  to: number;
  value: Decoration;
}

function marksIn(text: string, offset: number): Marked[] {
  const marks: Marked[] = [];

  const observation = OBSERVATION_LINE.exec(text);
  if (observation) {
    const bracket = 2 + observation[1].length + 2;
    marks.push({ from: offset + 2, to: offset + bracket, value: category });
    TRAILING_TAG.lastIndex = 0;
    for (let hit = TRAILING_TAG.exec(text); hit; hit = TRAILING_TAG.exec(text)) {
      marks.push({
        from: offset + hit.index + 1,
        to: offset + hit.index + hit[0].length,
        value: tag,
      });
    }
  } else {
    const relation = RELATION_LINE.exec(text);
    if (relation) {
      marks.push({ from: offset + 2, to: offset + 2 + relation[1].length, value: relationType });
    }
  }

  WIKILINK.lastIndex = 0;
  for (let hit = WIKILINK.exec(text); hit; hit = WIKILINK.exec(text)) {
    marks.push({ from: offset + hit.index, to: offset + hit.index + hit[0].length, value: wikilink });
  }
  return marks;
}

function decorate(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    let position = from;
    while (position <= to) {
      const line = view.state.doc.lineAt(position);
      const text = line.text;
      if (OBSERVATION_LINE.test(text)) builder.add(line.from, line.from, observationLine);
      else if (RELATION_LINE.test(text)) builder.add(line.from, line.from, relationLine);

      for (const mark of marksIn(text, line.from).sort((a, b) => a.from - b.from)) {
        builder.add(mark.from, mark.to, mark.value);
      }
      position = line.to + 1;
    }
  }
  return builder.finish();
}

export const semanticHighlight = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;

    constructor(view: EditorView) {
      this.decorations = decorate(view);
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) this.decorations = decorate(update.view);
    }
  },
  { decorations: (plugin) => plugin.decorations },
);
