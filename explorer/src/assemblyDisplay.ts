import type { Func, Instruction } from "./types";
import { hex } from "./types";

function readableName(name: string): string {
  return name
    .replace(/\s*\[clone[^\]]*\]/g, "")
    .replace(/\.(?:isra|constprop|part)\.\d+$/, "")
    .replace("tflite::reference_integer_ops::", "")
    .replace("tflite::", "")
    .replace("(anonymous namespace)::", "")
    .replace(/\(.*$/, "")
    .trim();
}

/** Presentation only: preserve measured addresses and raw disassembly in the
 * bundle. Resolve labels using the bundle's demangled symbols, not a guessed
 * demangling of the text. Unknown targets retain their exact numeric address.
 */
export function createAssemblyFormatter(functions: Func[]) {
  const ranges = functions
    .map((fn) => ({
      fn,
      start: BigInt(fn.address),
      end: BigInt(fn.address) + BigInt(fn.size),
    }))
    .sort((a, b) => (a.start > b.start ? -1 : a.start < b.start ? 1 : 0));
  const labels = new Map<string, string>();
  return (instruction: Instruction): string => {
    // objdump's comments may contain misleading pointer/symbol guesses for
    // register-relative accesses; those remain available in Original disassembly.
    const code = instruction.operands
      .split("#")[0]
      .replace(/\s*<[^>]*>/g, "")
      .trim();
    const { target, kind } = instruction.transfer;
    if (!target || !["branch", "jump", "call"].includes(kind)) return code;
    const operands = code.split(",");
    // Do not rewrite a register-relative indirect call as a direct transfer.
    if (!/^(?:0x)?[0-9a-f]+$/i.test(operands.at(-1)!.trim())) return code;
    operands[operands.length - 1] = hex(target);
    let label = labels.get(target);
    if (label === undefined) {
      const address = BigInt(target);
      const match = ranges.find(
        ({ start, end }) => start <= address && address < end,
      );
      const name = match ? readableName(match.fn.name) : "";
      label =
        name && !name.startsWith("_Z")
          ? name +
            (address === match!.start
              ? ""
              : ` + ${hex(String(address - match!.start))}`)
          : "";
      labels.set(target, label);
    }
    return `${operands.join(",")}${label ? `  # ${label}` : ""}`;
  };
}
