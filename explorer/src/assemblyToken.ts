export type AssemblyToken =
  | { kind: "register"; value: string }
  | { kind: "instruction"; value: string }
  | { kind: "address"; value: string };

// Columns are Monaco's one-based character offsets. Match the full mnemonic,
// including the dot, rather than relying on Monaco's default word boundaries.
export function assemblyTokenAt(
  text: string,
  column: number,
): AssemblyToken | null {
  const code = text.split("#")[0];
  // Offline listings include a retirement column; live listings omit it.
  const header = /^(0x[0-9a-f]+)\s+(?:[\d,]+\s+)?([a-z][a-z0-9.]*)\b/.exec(
    code,
  );
  if (!header) return null;
  const mnemonic = header[2];
  const start = header[0].length - mnemonic.length;
  const index = column - 1;
  if (start <= index && index < start + mnemonic.length)
    return { kind: "instruction", value: mnemonic };
  for (const match of code.matchAll(/\bx(?:[0-9]|[12][0-9]|3[01])\b/g)) {
    if (
      match.index! > start &&
      match.index! <= index &&
      index < match.index! + match[0].length
    )
      return { kind: "register", value: match[0] };
  }
  for (const match of code.matchAll(/\b0x[0-9a-f]+\b/gi)) {
    if (
      match.index! >= header[0].length &&
      match.index! <= index &&
      index < match.index! + match[0].length
    )
      return { kind: "address", value: BigInt(match[0]).toString() };
  }
  return null;
}

export function assemblyAddressRange(
  text: string,
  target: string,
): { start: number; end: number } | null {
  for (const match of text.split("#")[0].matchAll(/\b0x[0-9a-f]+\b/gi)) {
    const start = match.index! + 1;
    const token = assemblyTokenAt(text, start);
    if (token?.kind === "address" && token.value === target)
      return { start, end: start + match[0].length };
  }
  return null;
}
