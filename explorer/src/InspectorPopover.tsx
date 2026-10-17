import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { hex } from "./types";

export interface InspectorAnchor {
  pc: string;
  x: number;
  y: number;
}
export function InspectorPopover({
  selection,
  label,
  eyebrow,
  name,
  onClose,
  children,
  footer,
  className = "",
  context,
}: {
  selection: InspectorAnchor;
  label: string;
  eyebrow: string;
  name: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
  className?: string;
  context?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) close.current();
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
    };
    const scroll = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) close.current();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keyboard);
    document.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keyboard);
      document.removeEventListener("scroll", scroll, true);
    };
  }, []);
  const width = Math.min(380, window.innerWidth - 24);
  const left = Math.max(
    12,
    Math.min(selection.x, window.innerWidth - width - 12),
  );
  const top = Math.max(
    12,
    Math.min(selection.y + 14, window.innerHeight - 360),
  );
  return (
    <div
      ref={root}
      role="dialog"
      aria-label={label}
      className={`register-inspector ${className}`}
      style={{ left, top, width }}
    >
      <div className="register-inspector-header">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h3>
            {name} <span>{context || `at ${hex(selection.pc)}`}</span>
          </h3>
        </div>
        <button
          aria-label={`Close ${label.startsWith("Register") ? "register" : label.startsWith("Source variable") ? "source variable" : "instruction"} inspector`}
          onClick={onClose}
        >
          <X size={15} />
        </button>
      </div>
      <div className="register-inspector-body">{children}</div>
      <div className="register-inspector-footer">{footer}</div>
    </div>
  );
}
