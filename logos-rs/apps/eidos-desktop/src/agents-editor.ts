import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  keymap,
  lineNumbers,
} from "@codemirror/view";

/** Тёмная тема под палитру desktop (`style.css`). */
const eidosEditorTheme = EditorView.theme(
  {
    "&": {
      height: "100%",
      fontSize: "var(--text-md)",
      backgroundColor: "var(--bg)",
      color: "var(--text)",
    },
    ".cm-scroller": {
      fontFamily: 'ui-monospace, "Cascadia Code", monospace',
      lineHeight: "1.45",
    },
    ".cm-gutters": {
      backgroundColor: "var(--panel)",
      color: "var(--muted)",
      border: "none",
    },
    ".cm-activeLine": { backgroundColor: "rgba(91, 141, 239, 0.08)" },
    "&.cm-focused .cm-cursor": { borderLeftColor: "var(--accent)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
      backgroundColor: "rgba(91, 141, 239, 0.28) !important",
    },
    ".cm-activeLineGutter": { backgroundColor: "rgba(91, 141, 239, 0.12)" },
  },
  { dark: true },
);

let agentsEditorView: EditorView | null = null;

export function destroyAgentsEditor(): void {
  if (agentsEditorView) {
    agentsEditorView.destroy();
    agentsEditorView = null;
  }
}

export function getAgentsEditorText(): string {
  return agentsEditorView?.state.doc.toString() ?? "";
}

export function mountAgentsEditor(host: HTMLElement, initial: string): void {
  destroyAgentsEditor();
  const state = EditorState.create({
    doc: initial,
    extensions: [
      lineNumbers(),
      highlightActiveLine(),
      history(),
      yaml(),
      eidosEditorTheme,
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.lineWrapping,
    ],
  });
  agentsEditorView = new EditorView({ state, parent: host });
}

export function setAgentsEditorText(text: string): void {
  if (!agentsEditorView) return;
  agentsEditorView.dispatch({
    changes: {
      from: 0,
      to: agentsEditorView.state.doc.length,
      insert: text,
    },
  });
}
