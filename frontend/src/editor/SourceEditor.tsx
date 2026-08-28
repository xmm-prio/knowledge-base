/**
 * CodeMirror 6 over the document's raw Markdown.
 *
 * A source editor, not a WYSIWYG one (ADR-0005). What comes back out is what went in,
 * character for character, unless the person typed -- so saving an untouched document
 * produces no diff at all.
 *
 * The one place a byte could go missing is the line separator. `doc.toString()` always joins
 * with `\n` regardless of what the file used, so the separator is both pinned on the state
 * and read back through `sliceDoc`, which honours it.
 */

import { useEffect, useRef } from "react";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { bracketMatching, indentOnInput } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  rectangularSelection,
} from "@codemirror/view";
import { semanticHighlight } from "./semanticDecorations";
import { editorTheme, markdownHighlight } from "./theme";

/** Pin the separator so a CRLF document does not come back LF. */
export function lineSeparatorOf(text: string): string {
  return text.includes("\r\n") ? "\r\n" : "\n";
}

function extensions(text: string, onChange: (value: string) => void, readOnly: boolean) {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightActiveLine(),
    history(),
    drawSelection(),
    rectangularSelection(),
    indentOnInput(),
    bracketMatching(),
    keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
    markdown({ base: markdownLanguage }),
    markdownHighlight,
    semanticHighlight,
    editorTheme,
    EditorView.lineWrapping,
    EditorState.lineSeparator.of(lineSeparatorOf(text)),
    EditorState.readOnly.of(readOnly),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) onChange(update.state.sliceDoc());
    }),
  ];
}

export function SourceEditor({
  /** The document as it came off the wire. Changing it rebuilds the editor. */
  initialText,
  onChange,
  readOnly = false,
  className,
}: {
  initialText: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const notify = useRef(onChange);
  notify.current = onChange;

  useEffect(() => {
    const parent = host.current;
    if (!parent) return;
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: initialText,
        extensions: extensions(initialText, (value) => notify.current(value), readOnly),
      }),
    });
    return () => view.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialText, readOnly]);

  return <div ref={host} className={className} />;
}
