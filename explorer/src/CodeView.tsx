import { useEffect, useRef } from "react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/cpp/register.js";
import "monaco-editor/features/codeEditor/register.js";
import "monaco-editor/features/diffEditor/register.js";
import "monaco-editor/features/find/register.js";
import "monaco-editor/features/tokenization/register.js";
import "monaco-editor/features/gotoLine/register.js";
import "monaco-editor/features/clipboard/register.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { assemblyTokenAt, assemblyAddressRange } from "./assemblyToken";
import { sourceIdentifierAt } from "./sourceVariables";
(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};
monaco.languages.register({ id: "riscv" });
monaco.languages.setMonarchTokensProvider("riscv", {
  tokenizer: {
    root: [
      [/0x[0-9a-f]+/, "number.hex"],
      [/\b(?:x\d+|sp|ra)\b/, "variable"],
      [/\b(?:lb|lw|ld|lbu|lh|lhu|sw|sb|sd)\b/, "keyword"],
      [/\b(?:mulw?|addw?|subw?|bne|beq|jalr?|c\.\w+)\b/, "type"],
      [/#.*/, "comment"],
    ],
  },
});
monaco.editor.defineTheme("atlas", {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "comment", foreground: "647b8c" },
    { token: "keyword", foreground: "75b5d2" },
    { token: "number", foreground: "dfb978" },
    { token: "type", foreground: "c1a5d9" },
    { token: "variable", foreground: "b7cbd7" },
  ],
  colors: {
    "editor.background": "#111b25",
    "editor.foreground": "#c7d4df",
    "editorLineNumber.foreground": "#526675",
    "editorLineNumber.activeForeground": "#e4bb76",
    "editor.selectionBackground": "#294251",
    "editor.lineHighlightBackground": "#192735",
    "editorCursor.foreground": "#e4bb76",
    "editorGutter.background": "#111b25",
  },
});
export interface Decoration {
  line: number;
  className: string;
  glyph?: "breakpoint" | "stage-breakpoint" | "pc" | "last-pc";
  label?: string;
}
export function CodeView({
  text,
  language = "cpp",
  line = 1,
  decorations = [],
  onLine,
  onGutter,
  autoFocus = false,
  onRegister,
  onInstruction,
  onSourceVariable,
  onAddress,
  addressTargets,
  addressLines,
  revealRequest,
  debugGutter,
  label = "Source code",
}: {
  text: string;
  language?: string;
  line?: number;
  decorations?: Decoration[];
  onLine?: (line: number) => void;
  onGutter?: (line: number) => void;
  autoFocus?: boolean;
  onRegister?: (
    register: string,
    line: number,
    anchor: { x: number; y: number },
  ) => void;
  onInstruction?: (line: number, anchor: { x: number; y: number }) => void;
  onAddress?: (pc: string, line: number) => void;
  addressTargets?: ReadonlyMap<number, string>;
  addressLines?: ReadonlyMap<string, number>;
  revealRequest?: number;
  debugGutter?: { enabled: boolean; instructionLines: ReadonlySet<number> };
  onSourceVariable?: (
    name: string,
    line: number,
    anchor: { x: number; y: number },
  ) => void;
  label?: string;
}) {
  const container = useRef<HTMLDivElement>(null),
    editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null),
    marks = useRef<monaco.editor.IEditorDecorationsCollection | null>(null),
    links = useRef<monaco.editor.IEditorDecorationsCollection | null>(null),
    gutterLanes = useRef<monaco.editor.IEditorDecorationsCollection | null>(
      null,
    ),
    callback = useRef(onLine),
    gutterCallback = useRef(onGutter),
    registerCallback = useRef(onRegister),
    instructionCallback = useRef(onInstruction),
    sourceVariableCallback = useRef(onSourceVariable),
    addressCallback = useRef(onAddress),
    targets = useRef(addressTargets),
    targetLines = useRef(addressLines),
    debuggerGutter = useRef(debugGutter),
    currentDecorations = useRef(decorations);
  debuggerGutter.current = debugGutter;
  currentDecorations.current = decorations;
  callback.current = onLine;
  gutterCallback.current = onGutter;
  registerCallback.current = onRegister;
  instructionCallback.current = onInstruction;
  sourceVariableCallback.current = onSourceVariable;
  addressCallback.current = onAddress;
  targets.current = addressTargets;
  targetLines.current = addressLines;
  useEffect(() => {
    const model = monaco.editor.createModel("", language);
    const e = monaco.editor.create(container.current!, {
      model,
      theme: "atlas",
      readOnly: true,
      domReadOnly: true,
      automaticLayout: true,
      fontSize: 12,
      fontFamily: '"SFMono-Regular",Consolas,"Liberation Mono",monospace',
      lineHeight: 22,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      glyphMargin: true,
      renderLineHighlight: "gutter",
      padding: { top: 12 },
      wordWrap: "off",
      ariaLabel: label,
      stickyScroll: { enabled: false },
      overviewRulerLanes: 0,
      contextmenu: false,
      hover: { enabled: "off" },
    });
    editor.current = e;
    if (autoFocus) e.focus();
    marks.current = e.createDecorationsCollection();
    links.current = e.createDecorationsCollection();
    // Reserve both lanes immediately. Adding/removing dots never shifts code.
    const lanes = e.createDecorationsCollection(
      debugGutter
        ? [
            monaco.editor.GlyphMarginLane.Left,
            monaco.editor.GlyphMarginLane.Right,
          ].map((position) => ({
            range: new monaco.Range(1, 1, 1, 1),
            options: {
              glyphMarginClassName: "sim-gutter-reserved",
              glyphMargin: { position, persistLane: true },
            },
          }))
        : [],
    );
    gutterLanes.current = lanes;
    const preview = e.createDecorationsCollection();
    const gutterInfo = (n: number) =>
      currentDecorations.current
        .filter((d) => d.line === n && d.glyph)
        .map((d) => d.label)
        .filter(Boolean)
        .join(". ");
    const mouseMove = e.onMouseMove((event) => {
      const n = event.target.position?.lineNumber;
      const gutter = debuggerGutter.current;
      const isMargin =
        event.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN;
      if (!gutter || !isMargin || !n || !gutter.instructionLines.has(n)) {
        preview.clear();
        container.current!.removeAttribute("title");
        return;
      }
      const existing = currentDecorations.current.some(
        (d) =>
          d.line === n &&
          ["breakpoint", "stage-breakpoint"].includes(d.glyph || ""),
      );
      container.current!.title = [
        gutterInfo(n),
        gutter.enabled
          ? existing
            ? "Click to toggle address breakpoint (F9)"
            : "Add breakpoint (F9)"
          : "Pause execution to edit breakpoints",
      ]
        .filter(Boolean)
        .join(". ");
      preview.set(
        gutter.enabled && !existing
          ? [
              {
                range: new monaco.Range(n, 1, n, 1),
                options: {
                  glyphMarginClassName: "sim-breakpoint-preview-glyph",
                  glyphMargin: { position: monaco.editor.GlyphMarginLane.Left },
                },
              },
            ]
          : [],
      );
    });
    const mouseLeave = e.onMouseLeave(() => {
      preview.clear();
      container.current!.removeAttribute("title");
    });
    const toggleBreakpoint = (n: number) => {
      const gutter = debuggerGutter.current;
      if (!gutter || (gutter.enabled && gutter.instructionLines.has(n))) {
        e.setPosition({ lineNumber: n, column: 1 });
        e.focus();
        gutterCallback.current?.(n);
      }
      preview.clear();
    };
    if (debugGutter)
      e.addCommand(monaco.KeyCode.F9, () => {
        const n = e.getPosition()?.lineNumber;
        if (n) toggleBreakpoint(n);
      });
    const followAddress = (position: monaco.Position) => {
      if (language !== "riscv" || !addressCallback.current) return false;
      const token = assemblyTokenAt(
        model.getLineContent(position.lineNumber),
        position.column,
      );
      if (
        token?.kind !== "address" ||
        targets.current?.get(position.lineNumber) !== token.value
      )
        return false;
      // Navigate once: selecting the branch row in a separate state update
      // can race navigation to a different function.
      addressCallback.current(token.value, position.lineNumber);
      const address = "0x" + BigInt(token.value).toString(16);
      const row = targetLines.current
        ? (targetLines.current.get(token.value) || 0) - 1
        : model
            .getLinesContent()
            .findIndex((text) => text.startsWith(address + " "));
      if (row >= 0) {
        // Also reveal when the destination is already the current selection.
        e.setPosition({ lineNumber: row + 1, column: 1 });
        e.revealLineInCenterIfOutsideViewport(row + 1);
      }
      return true;
    };
    const inspectAt = (
      position: monaco.Position,
      anchor: { x: number; y: number },
    ) => {
      if (language === "cpp" && sourceVariableCallback.current) {
        const name = sourceIdentifierAt(
          model.getValue(),
          position.lineNumber,
          position.column,
        );
        if (name)
          sourceVariableCallback.current(name, position.lineNumber, anchor);
        return Boolean(name);
      }
      if (language !== "riscv") return false;
      const token = assemblyTokenAt(
        model.getLineContent(position.lineNumber),
        position.column,
      );
      if (token?.kind === "register")
        registerCallback.current?.(token.value, position.lineNumber, anchor);
      else if (token?.kind === "instruction")
        instructionCallback.current?.(position.lineNumber, anchor);
      return Boolean(token);
    };
    const listener = e.onMouseDown((event) => {
      const position = event.target.position;
      if (!position) return;
      if (
        event.target.type ===
          monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN &&
        gutterCallback.current
      ) {
        toggleBreakpoint(position.lineNumber);
        return;
      }
      if (event.target.type === monaco.editor.MouseTargetType.CONTENT_TEXT)
        e.setPosition(position);
      if (
        event.target.type === monaco.editor.MouseTargetType.CONTENT_TEXT &&
        followAddress(position)
      ) {
        event.event.preventDefault();
        return;
      }
      callback.current?.(position.lineNumber);
      if (event.target.type === monaco.editor.MouseTargetType.CONTENT_TEXT)
        inspectAt(position, {
          x: event.event.browserEvent.clientX,
          y: event.event.browserEvent.clientY,
        });
    });
    const keyboard = e.onKeyDown((event) => {
      const position = e.getPosition();
      if (
        (!registerCallback.current &&
          !instructionCallback.current &&
          !sourceVariableCallback.current &&
          !addressCallback.current) ||
        event.keyCode !== monaco.KeyCode.Enter ||
        !position
      )
        return;
      if (followAddress(position)) {
        event.preventDefault();
        return;
      }
      const visible = e.getScrolledVisiblePosition(position);
      if (visible) {
        event.preventDefault();
        callback.current?.(position.lineNumber);
        const bounds = container.current!.getBoundingClientRect();
        inspectAt(position, {
          x: bounds.left + visible.left,
          y: bounds.top + visible.top + visible.height,
        });
      }
    });
    return () => {
      mouseMove.dispose();
      mouseLeave.dispose();
      preview.clear();
      lanes.clear();
      listener.dispose();
      keyboard.dispose();
      e.dispose();
      model.dispose();
    };
  }, [language, label]);
  useEffect(() => {
    const m = editor.current?.getModel();
    if (m && m.getValue() !== text) m.setValue(text);
    if (debugGutter)
      gutterLanes.current?.set(
        [
          monaco.editor.GlyphMarginLane.Left,
          monaco.editor.GlyphMarginLane.Right,
        ].map((position) => ({
          range: new monaco.Range(1, 1, 1, 1),
          options: {
            glyphMarginClassName: "sim-gutter-reserved",
            glyphMargin: { position, persistLane: true },
          },
        })),
      );
  }, [text, language, label]);
  useEffect(() => {
    const e = editor.current;
    if (e) {
      const n = Math.min(Math.max(line, 1), e.getModel()?.getLineCount() || 1);
      if (debugGutter) e.setPosition({ lineNumber: n, column: 1 });
      e.revealLineInCenterIfOutsideViewport(n);
    }
  }, [line, text, language, label, revealRequest]);
  useEffect(() => {
    marks.current?.set(
      decorations.map((d) => ({
        range: new monaco.Range(d.line, 1, d.line, 1),
        options: {
          isWholeLine: true,
          className: d.className,
          glyphMarginClassName: debugGutter
            ? d.glyph
              ? `sim-${d.glyph}-glyph`
              : undefined
            : d.className.includes("sim-breakpoint")
              ? "sim-breakpoint-glyph"
              : d.className === "source-linked"
                ? "source-match-glyph"
                : d.className.includes("selected")
                  ? "selection-glyph"
                  : undefined,
          glyphMargin:
            debugGutter && d.glyph
              ? {
                  position: ["pc", "last-pc"].includes(d.glyph)
                    ? monaco.editor.GlyphMarginLane.Right
                    : monaco.editor.GlyphMarginLane.Left,
                }
              : undefined,
          lineNumberClassName: d.glyph === "pc" ? "sim-pc-number" : undefined,
          glyphMarginHoverMessage: d.label ? { value: d.label } : undefined,
        },
      })),
    );
  }, [decorations, text]);
  useEffect(() => {
    const lines = text.split("\n");
    links.current?.set(
      [...(addressTargets || [])].flatMap(([line, target]) => {
        const range = assemblyAddressRange(lines[line - 1] || "", target);
        return range
          ? [
              {
                range: new monaco.Range(line, range.start, line, range.end),
                options: { inlineClassName: "assembly-address-link" },
              },
            ]
          : [];
      }),
    );
  }, [addressTargets, text, language, label]);
  return <div className="code-editor" ref={container} />;
}
export function DiffView({ before, after }: { before: string; after: string }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const e = monaco.editor.createDiffEditor(container.current!, {
      theme: "atlas",
      readOnly: true,
      automaticLayout: true,
      fontSize: 12,
      minimap: { enabled: false },
      renderSideBySide: true,
      scrollBeyondLastLine: false,
      ariaLabel: "Compiler stage diff",
      hover: { enabled: "off" },
    });
    const original = monaco.editor.createModel(before, "plaintext"),
      modified = monaco.editor.createModel(after, "plaintext");
    e.setModel({ original, modified });
    return () => {
      e.dispose();
      original.dispose();
      modified.dispose();
    };
  }, [before, after]);
  return <div className="code-editor" ref={container} />;
}
