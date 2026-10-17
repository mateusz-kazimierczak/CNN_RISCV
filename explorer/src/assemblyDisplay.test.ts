import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import type { Evidence, Func, Instruction } from "./types";
import { createAssemblyFormatter } from "./assemblyDisplay";
const fn = (name: string, address: string, size: number) =>
  ({ name, address, size }) as Func;
const insn = (operands: string, target: string | null, kind = "branch") =>
  ({ operands, transfer: { target, kind } }) as Instruction;
describe("readable assembly targets", () => {
  it("uses demangled function labels and byte offsets without changing raw evidence", () => {
    const format = createAssemblyFormatter([
      fn(
        "tflite::reference_integer_ops::ConvPerChannel(int) [clone .isra.0]",
        "2147506922",
        768,
      ),
    ]);
    const i = insn(
      "x27,x14,80005c94 <_ZN6tfliteSomething.isra.0+0x1aa>",
      "2147507348",
    );
    expect(format(i)).toBe("x27,x14,0x80005c94  # ConvPerChannel + 0x1aa");
    expect(i.operands).toContain("<_ZN6tfliteSomething");
    expect(i.transfer.target).toBe("2147507348");
  });
  it("shows exact call entries, unknown addresses, and preserves indirect operands", () => {
    const format = createAssemblyFormatter([
      fn("tflite::MultiplyByQuantizedMultiplier(int, int, int)", "4096", 64),
    ]);
    expect(format(insn("x1,1000 <_Zmangled>", "4096", "call"))).toBe(
      "x1,0x1000  # MultiplyByQuantizedMultiplier",
    );
    expect(format(insn("x1,2000 <_Zunknown>", "8192", "call"))).toBe(
      "x1,0x2000",
    );
    expect(format(insn("x1,0(x8)", "4096", "call"))).toBe("x1,0(x8)");
    expect(format(insn("x1,0(x8)", null, "call"))).toBe("x1,0(x8)");
  });
  it("omits noisy objdump annotations on loads and uses exact 64-bit offsets", () => {
    const format = createAssemblyFormatter([
      fn("largeAddress()", "9007199254740993", 64),
    ]);
    expect(
      format(
        insn("x23,0(x17) # ffffffff80000000 <__stack_top+0x123>", null, "next"),
      ),
    ).toBe("x23,0(x17)");
    expect(
      format(
        insn("x1,20000000000003 <symbol+0x2>", "9007199254740995", "call"),
      ),
    ).toBe("x1,0x20000000000003  # largeAddress + 0x2");
  });
  it("does not pretend to demangle unavailable function names", () => {
    const format = createAssemblyFormatter([fn("_Zunavailable", "4096", 64)]);
    expect(format(insn("x1,1000 <_Zunavailable>", "4096", "call"))).toBe(
      "x1,0x1000",
    );
  });
});
const bundlePath = new URL("../../build/explorer/B0.zip", import.meta.url);
it.skipIf(!existsSync(bundlePath))(
  "real B0: the convolution branch has a readable label and matching address",
  () => {
    const files = unzipSync(new Uint8Array(readFileSync(bundlePath)), {
      filter: (f) => f.name === "evidence.json",
    });
    const data = JSON.parse(strFromU8(files["evidence.json"])) as Evidence;
    const format = createAssemblyFormatter(data.functions);
    expect(format(data.instructions[String(0x80005cac)])).toBe(
      "x27,x14,0x80005c94  # ConvPerChannel + 0x1aa",
    );
    expect(format(data.instructions[String(0x80005cec)])).toBe(
      "x1,0x8000dcdc  # MultiplyByQuantizedMultiplier",
    );
  },
);
