import { expect, it } from "vitest";
import { DEFAULT_PANES, resizePanes } from "./layout";
it("gives assembly the largest first pane and only exchanges adjacent widths", () => {
  expect(DEFAULT_PANES).toEqual([50, 30]);
  expect(resizePanes(DEFAULT_PANES, 0, 8)).toEqual([58, 22]);
  expect(resizePanes(DEFAULT_PANES, 1, 4)).toEqual([50, 34]);
  expect(resizePanes(DEFAULT_PANES, 0, 100)).toEqual([60, 20]);
  expect(resizePanes(DEFAULT_PANES, 0, -100)).toEqual([32, 48]);
  expect(resizePanes(DEFAULT_PANES, 1, 100)).toEqual([50, 36]);
  expect(resizePanes(DEFAULT_PANES, 1, -100)).toEqual([50, 20]);
});
