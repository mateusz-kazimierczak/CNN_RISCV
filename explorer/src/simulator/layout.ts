// Adjacent panes exchange width; the third pane stays put. Percentages exclude
// the fixed separator tracks, and the assembly pane remains the main workspace.
export const DEFAULT_PANES = [50, 30] as const;
export function resizePanes(
  widths: readonly number[],
  boundary: number,
  delta: number,
): number[] {
  const [assembly, source] = widths;
  const model = 100 - assembly - source;
  if (boundary === 0) {
    const change = Math.max(32 - assembly, Math.min(source - 20, delta));
    return [assembly + change, source - change];
  }
  const change = Math.max(20 - source, Math.min(model - 14, delta));
  return [assembly, source + change];
}
