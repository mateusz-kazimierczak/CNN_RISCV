import type { Evidence, RegisterEvidence, RegisterLocation } from "./types";

export function locationsAt(
  data: RegisterEvidence | undefined,
  register: string,
  pc: string,
): RegisterLocation[] {
  if (!data) return [];
  const address = BigInt(pc);
  return (data.locations[register] || []).filter(
    (location) =>
      BigInt(location.low) <= address && address < BigInt(location.high),
  );
}

export interface ExpressionStep {
  pc: string;
  description: string;
}
export interface RegisterExpression {
  text: string;
  key: string;
  precedence: number;
  steps: ExpressionStep[];
  word32: boolean;
}
export type RegisterAnalysis = Pick<
  Evidence,
  "registers" | "functions" | "instructions"
>;

const register = /^x(?:[0-9]|[12][0-9]|3[01])$/;
const callerSaved = new Set([
  1, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 28, 29, 30, 31,
]);
// Only these instructions may be crossed without invalidating unrelated registers.
// Unknown/custom instructions may have additional effects: stop at those.
const writesFirst =
  /^(?:add|sub|mul|div|divu|rem|remu|and|or|xor|sll|srl|sra|slt|sltu|addi|andi|ori|xori|slli|srli|srai|slti|sltiu|addw|subw|mulw|divw|divuw|remw|remuw|addiw|sllw|srlw|sraw|slliw|srliw|sraiw|lui|auipc|lb|lbu|lh|lhu|lw|lwu|ld|mv|li|neg|negw|not|sext\.w|c\.(?:mv|li|lui|add|addw|sub|subw|and|or|xor|addi|addiw|addi16sp|addi4spn|slli|srli|srai|andi|lw|ld|lwsp|ldsp))$/;
const noWrite =
  /^(?:sb|sh|sw|sd|beq|bne|blt|bge|bltu|bgeu|beqz|bnez|blez|bgez|bltz|bgtz|j|nop|fence|fence\.i|c\.(?:sw|sd|swsp|sdsp|beqz|bnez|j|nop))$/;

const uniqueSteps = (steps: ExpressionStep[]) => [
  ...new Map(
    steps.map((step) => [`${step.pc}:${step.description}`, step]),
  ).values(),
];

/** A bounded, demand-driven reaching-definition analysis. All incoming static
 * paths must agree; histograms never select a path. Cycles without a definition
 * are traversed once, while recursive value-changing cycles remain unknown.
 * Source names refer to values at the listed DWARF seed addresses.
 */
export function inferRegisterExpression(
  data: RegisterAnalysis,
  targetRegister: string,
  targetPc: string,
): RegisterExpression | null {
  if (!data.registers || !register.test(targetRegister)) return null;
  const candidates = data.functions.filter((fn) => fn.pcs.includes(targetPc));
  if (candidates.length !== 1 || !candidates[0].cfg.complete) return null;
  const fn = candidates[0];
  const blocks = new Map(fn.cfg.blocks.map((block) => [block.id, block]));
  const at = new Map<string, { block: string; index: number }>();
  const predecessors = new Map<string, string[]>();
  for (const block of blocks.values()) {
    block.pcs.forEach((pc, index) => at.set(pc, { block: block.id, index }));
    for (const edge of block.successors)
      predecessors.set(edge.to, [
        ...(predecessors.get(edge.to) || []),
        block.id,
      ]);
  }
  let budget = 12000;
  const active = new Set<string>();

  function seed(reg: string, pc: string): RegisterExpression | null {
    const locations = locationsAt(data.registers, reg, pc);
    if (locations.length !== 1 || locations[0].kind !== "value") return null;
    const variable = data.registers!.variables[locations[0].variableId];
    if (!variable) return null;
    return {
      text: variable.name,
      key: `variable:${variable.id}@${pc}`,
      precedence: 3,
      steps: [{ pc, description: `DWARF: ${reg} holds ${variable.name}` }],
      word32: false,
    };
  }
  function constant(text: string): RegisterExpression | null {
    try {
      const value = BigInt(text).toString();
      return {
        text: value,
        key: `constant:${value}`,
        precedence: 3,
        steps: [],
        word32: false,
      };
    } catch {
      return null;
    }
  }
  function resolve(
    reg: string,
    pc: string,
    depth: number,
  ): RegisterExpression | null {
    if (--budget < 0 || depth > 24) return null;
    if (reg === "x0") return constant("0");
    if (!register.test(reg)) return null;
    // Direct metadata is authoritative; never replace a partial/address mapping
    // with an inferred value or resolve conflicting inline-frame locations.
    const direct = locationsAt(data.registers, reg, pc);
    if (direct.length) return seed(reg, pc);
    const start = at.get(pc);
    if (!start) return null;
    const key = `${reg}@${pc}`;
    if (active.has(key)) return null;
    active.add(key);
    const visited = new Set<string>();
    const results: RegisterExpression[] = [];
    const pending = [start];
    let unknown = false;

    function scan(blockId: string, end: number) {
      if (--budget < 0) {
        unknown = true;
        return;
      }
      const visit = `${blockId}:${end}`;
      if (visited.has(visit)) return;
      visited.add(visit);
      const block = blocks.get(blockId)!;
      for (let index = end - 1; index >= 0; index--) {
        if (--budget < 0) {
          unknown = true;
          return;
        }
        const previousPc = block.pcs[index];
        const instruction = data.instructions[previousPc];
        const mnemonic = instruction.mnemonic;
        const operands = instruction.operands
          .split("#")[0]
          .split(",")
          .map((s) => s.trim());
        const transfer = instruction.transfer.kind;
        if (transfer === "call") {
          if (
            callerSaved.has(Number(reg.slice(1))) ||
            (["jal", "jalr"].includes(mnemonic) && operands[0] === reg)
          ) {
            unknown = true;
            return;
          }
        } else if (writesFirst.test(mnemonic)) {
          if (operands[0] === reg) {
            const value = evaluate(mnemonic, operands, previousPc, depth + 1);
            if (value) results.push(value);
            else unknown = true;
            return;
          }
        } else if (
          !noWrite.test(mnemonic) &&
          transfer !== "branch" &&
          transfer !== "jump"
        ) {
          unknown = true;
          return;
        }
        const locations = locationsAt(data.registers, reg, previousPc);
        if (locations.length) {
          const value = seed(reg, previousPc);
          if (value) results.push(value);
          else unknown = true;
          return;
        }
      }
      const incoming = predecessors.get(blockId) || [];
      // The entry has an external predecessor even if a backedge targets it.
      if (!incoming.length || block.start === fn.address) {
        unknown = true;
        return;
      }
      for (const predecessor of incoming)
        pending.push({
          block: predecessor,
          index: blocks.get(predecessor)!.pcs.length,
        });
    }
    while (pending.length && !unknown) {
      const next = pending.pop()!;
      scan(next.block, next.index);
    }
    active.delete(key);
    if (
      unknown ||
      !results.length ||
      results.some((value) => value.key !== results[0].key)
    )
      return null;
    return {
      ...results[0],
      steps: uniqueSteps(results.flatMap((value) => value.steps)),
    };
  }

  function evaluate(
    mnemonic: string,
    operands: string[],
    pc: string,
    depth: number,
  ): RegisterExpression | null {
    const compressed = mnemonic.startsWith("c.");
    const op = mnemonic.replace(/^c\./, "");
    const [destination, a, b] = operands;
    let left: RegisterExpression | null;
    let right: RegisterExpression | null = null;
    let operator = "";
    if (op === "mv") left = resolve(a, pc, depth);
    else if (op === "li") left = constant(a);
    else if (["add", "addw", "sub", "subw", "mul", "mulw"].includes(op)) {
      left = resolve(compressed ? destination : a, pc, depth);
      right = resolve(compressed ? a : b, pc, depth);
      operator = op.startsWith("add") ? "+" : op.startsWith("sub") ? "-" : "*";
    } else if (op === "addi" || op === "addiw") {
      left = resolve(compressed ? destination : a, pc, depth);
      right = constant(compressed ? a : b);
      operator = "+";
    } else return null; // Loads, shifts and other transforms need separate semantics.
    if (!left || (operator && !right)) return null;
    let result = left;
    if (right) {
      const precedence = operator === "*" ? 2 : 1;
      const wrap = (value: RegisterExpression, rhs = false) =>
        value.precedence < precedence ||
        (rhs && value.precedence === precedence)
          ? `(${value.text})`
          : value.text;
      result = {
        text: `${wrap(left)} ${operator} ${wrap(right, true)}`,
        key: `${op}(${left.key},${right.key})`,
        precedence,
        steps: [...left.steps, ...right.steps],
        word32: left.word32 || right.word32,
      };
    }
    if (result.text.length > 180) return null;
    return {
      ...result,
      steps: uniqueSteps([
        ...result.steps,
        { pc, description: `${mnemonic} ${operands.join(",")}` },
      ]),
      word32: result.word32 || ["addw", "subw", "mulw", "addiw"].includes(op),
    };
  }
  return resolve(targetRegister, targetPc, 0);
}
