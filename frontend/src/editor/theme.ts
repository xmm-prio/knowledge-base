/** The editor's look, in the same vocabulary as the rest of the app. */

import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

export const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "13.5px",
    backgroundColor: "var(--c-bg)",
    color: "var(--c-text)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--f-mono)",
    lineHeight: "1.7",
    overflow: "auto",
  },
  ".cm-content": { padding: "var(--s-4) 0", caretColor: "var(--c-accent)" },
  ".cm-line": { padding: "0 var(--s-4)" },
  ".cm-gutters": {
    backgroundColor: "var(--c-bg-sunken)",
    borderRight: "1px solid var(--c-border)",
    color: "var(--c-text-faint)",
  },
  ".cm-activeLine": { backgroundColor: "rgba(47, 109, 240, 0.04)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--c-bg-active)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
    backgroundColor: "var(--c-accent-soft)",
  },

  ".cm-observation-line": { backgroundColor: "rgba(47, 109, 240, 0.045)" },
  ".cm-relation-line": { backgroundColor: "rgba(43, 122, 75, 0.05)" },
  ".cm-observation-category": {
    color: "var(--c-accent-text)",
    fontWeight: "600",
  },
  ".cm-observation-tag": { color: "var(--c-warn)" },
  ".cm-relation-type": { color: "var(--c-ok)", fontWeight: "600" },
  ".cm-wikilink": {
    color: "var(--c-accent-text)",
    textDecoration: "underline",
    textDecorationStyle: "dotted",
  },
});

export const markdownHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: tags.heading, color: "#1f1f1c", fontWeight: "700" },
    { tag: tags.strong, fontWeight: "700" },
    { tag: tags.emphasis, fontStyle: "italic" },
    { tag: tags.link, color: "var(--c-accent-text)" },
    { tag: tags.url, color: "var(--c-text-muted)" },
    { tag: tags.monospace, color: "#b3392c" },
    { tag: tags.quote, color: "var(--c-text-muted)" },
    { tag: tags.list, color: "var(--c-text-muted)" },
    { tag: tags.contentSeparator, color: "var(--c-text-faint)" },
    { tag: tags.comment, color: "var(--c-text-faint)" },
  ]),
);
