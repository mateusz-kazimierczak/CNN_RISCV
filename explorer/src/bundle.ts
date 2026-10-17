import { Unzip, UnzipInflate, strFromU8 } from "fflate";
import type { Evidence } from "./types";
import { supportedMnemonics } from "./instructionHelp";
export const LIMITS = {
  compressed: 256 * 1024 ** 2,
  total: 512 * 1024 ** 2,
  entry: 128 * 1024 ** 2,
  entries: 10000,
};
const uint = (v: unknown): v is string =>
  typeof v === "string" &&
  /^(0|[1-9][0-9]{0,19})$/.test(v) &&
  BigInt(v) <= 18446744073709551615n;
function assert(ok: unknown, message: string): asserts ok {
  if (!ok) throw new Error(message);
}
const own = (o: object, k: string) => Object.hasOwn(o, k);
export function safePath(path: string) {
  return (
    !!path &&
    !path.startsWith("/") &&
    !path.includes("\\") &&
    !path.includes("\0") &&
    !path.split("/").some((p) => !p || p === "." || p === "..") &&
    !/^[a-z]:/i.test(path)
  );
}
export function validateEvidence(
  d: Evidence,
  files: Record<string, Uint8Array>,
) {
  assert(d && d.schemaVersion === 2, "Unsupported evidence schema");
  assert(
    Array.isArray(d.events) &&
      Array.isArray(d.functions) &&
      Array.isArray(d.graph?.nodes) &&
      Array.isArray(d.graph?.tensors) &&
      Array.isArray(d.graph?.edges) &&
      Array.isArray(d.executionPlan?.units),
    "Missing evidence collections",
  );
  assert(
    d.instructions &&
      d.sources &&
      Array.isArray(d.compilerUnits) &&
      Array.isArray(d.annotations) &&
      d.provenance?.hashes,
    "Missing static evidence",
  );
  assert(
    d.provenance.loadable_sections_identical !== false &&
      d.provenance.repeat_histograms_identical !== false,
    "Unvalidated capture",
  );
  for (const key of Object.keys(d.instructions))
    assert(uint(key), "Invalid PC");
  const unique = (items: { id: string }[], name: string) => {
    assert(
      items.every((x) => typeof x.id === "string"),
      "Invalid " + name + " ID",
    );
    const s = new Set(items.map((x) => x.id));
    assert(s.size === items.length, "Duplicate " + name);
    return s;
  };
  const fids = unique(d.functions, "function"),
    eids = unique(d.events, "event"),
    nids = unique(d.graph.nodes, "node"),
    uids = unique(d.executionPlan.units, "execution unit");
  const hasPc = (pc: string) =>
    typeof pc === "string" && own(d.instructions, pc);
  const pcs = (values: string[]) =>
    Array.isArray(values) &&
    new Set(values).size === values.length &&
    values.every(hasPc);
  const sourceExists = (path: string) => own(d.sources, path);
  for (const [pc, i] of Object.entries(d.instructions)) {
    assert(
      i.pc === pc &&
        [2, 4].includes(i.length) &&
        /^0x[0-9a-f]+$/.test(i.bits) &&
        typeof i.mnemonic === "string" &&
        typeof i.operands === "string" &&
        typeof i.category === "string",
      "Invalid instruction",
    );
    assert(
      Array.isArray(i.functionIds) &&
        i.functionIds.every((f) => fids.has(f)) &&
        (!i.functionId || i.functionIds.includes(i.functionId)),
      "Invalid instruction function reference",
    );
    assert(
      i.transfer &&
        typeof i.transfer.kind === "string" &&
        (i.transfer.target === null || uint(i.transfer.target)),
      "Invalid transfer",
    );
    assert(
      Array.isArray(i.frames) &&
        i.frames.every(
          (f) =>
            typeof f.function === "string" &&
            (f.file === null ||
              (sourceExists(f.file) &&
                Number.isSafeInteger(f.line) &&
                Number(f.line) > 0)),
        ),
      "Invalid source frame",
    );
  }
  for (const f of d.functions) {
    assert(
      uint(f.address) &&
        Number.isSafeInteger(f.size) &&
        f.size > 0 &&
        pcs(f.pcs) &&
        Array.isArray(f.aliases) &&
        Array.isArray(f.linkageNames) &&
        typeof f.name === "string",
      "Invalid function",
    );
    const b = unique(f.cfg.blocks, "block"),
      l = unique(f.cfg.loops, "loop"),
      fp = new Set(f.pcs);
    for (const block of f.cfg.blocks)
      assert(
        pcs(block.pcs) &&
          block.pcs.every((p) => fp.has(p)) &&
          block.successors.every((e) => b.has(e.to)),
        "Invalid basic block",
      );
    for (const loop of f.cfg.loops) {
      assert(
        pcs(loop.pcs) &&
          loop.pcs.every((p) => fp.has(p)) &&
          pcs(loop.exclusivePcs) &&
          loop.exclusivePcs.every((p) => loop.pcs.includes(p)),
        "Invalid loop instructions",
      );
      assert(
        loop.blocks.every((id) => b.has(id)) &&
          loop.children.every((id) => l.has(id) && id !== loop.id) &&
          (!loop.parent || l.has(loop.parent)) &&
          (!loop.header || b.has(loop.header)) &&
          loop.latches.every((id) => b.has(id)),
        "Invalid loop relationship",
      );
    }
  }
  for (const e of d.events) {
    assert(
      uint(e.total) &&
        e.counts &&
        !e.id.startsWith("logical:") &&
        typeof e.name === "string" &&
        (!e.nodeId || nids.has(e.nodeId)) &&
        [
          "inference",
          "setup",
          "execution-unit",
          "invocation-overhead",
        ].includes(e.scope) &&
        ["measured", "derived"].includes(e.evidence) &&
        (e.scope === "execution-unit"
          ? typeof e.unitId === "string" && uids.has(e.unitId)
          : e.unitId === null && e.nodeId === null),
      "Invalid event",
    );
    assert(
      e.scope === "invocation-overhead"
        ? e.evidence === "derived"
        : e.evidence === "measured" &&
            e.complete === true &&
            e.status === "0" &&
            typeof e.entry === "string" &&
            hasPc(e.entry) &&
            typeof e.returnPc === "string" &&
            hasPc(e.returnPc),
      "Incomplete, failed or invalid measurement boundary",
    );
    let total = 0n;
    for (const [pc, v] of Object.entries(e.counts)) {
      assert(
        hasPc(pc) &&
          uint(v) &&
          (!BigInt(v) ||
            (d.instructions[pc].category !== "unknown" &&
              supportedMnemonics.has(d.instructions[pc].mnemonic))),
        "Invalid event PC/count or unknown executed encoding",
      );
      total += BigInt(v);
    }
    assert(total === BigInt(e.total), "Event totals do not reconcile");
    assert(
      e.mix && Object.values(e.mix).every(uint),
      "Invalid instruction mix",
    );
    if (Object.keys(e.mix).length)
      assert(
        Object.values(e.mix).reduce((n, v) => n + BigInt(v), 0n) === total,
        "Instruction mix does not reconcile",
      );
  }
  const allocation = d.events.filter((e) => e.scope === "setup"),
    inference = d.events.filter((e) => e.scope === "inference"),
    residual = d.events.filter((e) => e.scope === "invocation-overhead");
  assert(
    inference.length === 1 && residual.length === 1 && allocation.length <= 1,
    "Invalid measurement scopes",
  );
  const invoke = inference[0],
    overhead = residual[0],
    allocate = allocation[0];
  assert(
    uint(d.totals.inference) &&
      uint(d.totals.overhead) &&
      d.totals.inference === invoke.total &&
      d.totals.overhead === overhead.total &&
      (allocate
        ? uint(d.totals.allocation) && d.totals.allocation === allocate.total
        : d.totals.allocation === null),
    "Invalid model totals",
  );
  const operators = d.events.filter((e) => e.scope === "execution-unit");
  const claimed = new Set<string>();
  for (const [order, u] of d.executionPlan.units.entries()) {
    assert(
      u.order === order &&
        typeof u.implementation === "string" &&
        u.implementation.length > 0 &&
        typeof u.arithmetic_backend === "string" &&
        u.arithmetic_backend.length > 0 &&
        typeof u.symbol === "string" &&
        Array.isArray(u.notes) &&
        u.notes.every((n) => typeof n === "string") &&
        Array.isArray(u.nodes) &&
        u.nodes.length > 0 &&
        new Set(u.nodes).size === u.nodes.length &&
        u.nodes.every((n) => nids.has(n)) &&
        Array.isArray(u.eventIds) &&
        new Set(u.eventIds).size === u.eventIds.length,
      "Invalid execution unit",
    );
    for (const id of u.eventIds) {
      const e = d.events.find((e) => e.id === id);
      assert(
        eids.has(id) &&
          e?.scope === "execution-unit" &&
          e.unitId === u.id &&
          !claimed.has(id) &&
          e.evidence === "measured" &&
          e.nodeId === (u.nodes.length === 1 ? u.nodes[0] : null),
        "Invalid execution event relationship",
      );
      claimed.add(id);
    }
    assert(
      u.work &&
        ["derived", "unavailable"].includes(u.work.evidence) &&
        (u.work.logical_macs === null || uint(u.work.logical_macs)) &&
        (u.work.executed_products === null || uint(u.work.executed_products)),
      "Invalid work estimate",
    );
    if (u.source)
      assert(
        sourceExists(u.source.file) &&
          Number.isSafeInteger(u.source.line) &&
          u.source.line > 0 &&
          Number.isSafeInteger(u.source.end_line) &&
          u.source.end_line >= u.source.line,
        "Invalid generated source region",
      );
  }
  assert(claimed.size === operators.length, "Unclaimed execution events");
  const reconciled: Record<string, bigint> = Object.create(null);
  for (const e of [...operators, overhead])
    for (const [pc, n] of Object.entries(e.counts))
      reconciled[pc] = (reconciled[pc] || 0n) + BigInt(n);
  for (const pc of new Set([
    ...Object.keys(reconciled),
    ...Object.keys(invoke.counts),
  ]))
    assert(
      (reconciled[pc] || 0n) === BigInt(invoke.counts[pc] || "0"),
      "Operator counts do not reconcile per PC",
    );
  for (const [id, s] of Object.entries(d.sources))
    assert(
      s.id === id &&
        s.path === id &&
        (s.archivePath === null ||
          (safePath(s.archivePath) &&
            own(files, s.archivePath) &&
            typeof s.sha256 === "string")),
      "Invalid source snapshot",
    );
  const tids = new Set(d.graph.tensors.map((t) => t.id));
  assert(tids.size === d.graph.tensors.length, "Duplicate tensor");
  for (const t of d.graph.tensors)
    assert(
      Number.isSafeInteger(t.id) &&
        t.shape.every(Number.isSafeInteger) &&
        (!t.producer || nids.has(t.producer)) &&
        t.consumers.every((id) => nids.has(id)),
      "Invalid tensor",
    );
  for (const n of d.graph.nodes) {
    const expected = d.executionPlan.units
      .filter((u) => u.nodes.includes(n.id))
      .map((u) => u.id);
    assert(
      Array.isArray(n.unitIds) &&
        n.unitIds.length === expected.length &&
        n.unitIds.every((id, i) => id === expected[i]) &&
        (expected.length
          ? n.disposition === "executed"
          : n.disposition === "eliminated" &&
            typeof n.reason === "string" &&
            n.reason.length > 0) &&
        [...n.inputs, ...n.outputs].every((id) => tids.has(id)) &&
        uint(n.logical_macs) &&
        (n.executed_products === null || uint(n.executed_products)),
      "Invalid graph node",
    );
  }
  for (const u of d.executionPlan.units)
    assert(
      [...u.inputs, ...u.outputs].every((t) => tids.has(t)),
      "Invalid execution operand",
    );
  if (d.memoryPlan) {
    const m = d.memoryPlan;
    const size = (v: number) => Number.isSafeInteger(v) && v >= 0;
    assert(
      size(m.arena_bytes) &&
        size(m.rodata_bytes) &&
        Array.isArray(m.requests) &&
        Array.isArray(m.placements) &&
        Array.isArray(m.tensors) &&
        Array.isArray(m.aliases) &&
        Array.isArray(m.scratch) &&
        m.summary &&
        size(m.summary.peak_live_activation_bytes) &&
        size(m.summary.peak_live_scratch_bytes),
      "Invalid memory plan",
    );
    const names = new Set(m.requests.map((r) => r.name));
    assert(
      names.size === m.requests.length &&
        m.placements.length === names.size &&
        new Set(m.placements.map((p) => p.name)).size === names.size,
      "Invalid memory placement inventory",
    );
    for (const r of m.requests) {
      const p = m.placements.find((p) => p.name === r.name);
      assert(
        p &&
          size(r.size_bytes) &&
          Number.isSafeInteger(r.start) &&
          r.start >= -1 &&
          Number.isSafeInteger(r.end) &&
          r.end >= r.start &&
          r.end <= d.executionPlan.units.length &&
          size(r.alignment) &&
          r.alignment > 0 &&
          ["activation", "scratch"].includes(r.category) &&
          (r.size_bytes === 0
            ? p.offset === null
            : typeof p.offset === "number" &&
              size(p.offset) &&
              p.offset % r.alignment === 0 &&
              p.offset + r.size_bytes <= m.arena_bytes),
        "Invalid memory lifetime/placement",
      );
    }
    for (let i = 0; i < m.requests.length; i++)
      for (let j = i + 1; j < m.requests.length; j++) {
        const a = m.requests[i],
          b = m.requests[j];
        const x = m.placements.find((p) => p.name === a.name)!.offset,
          y = m.placements.find((p) => p.name === b.name)!.offset;
        assert(
          x === null ||
            y === null ||
            a.end < b.start ||
            b.end < a.start ||
            x + a.size_bytes <= y ||
            y + b.size_bytes <= x,
          "Overlapping live memory groups",
        );
      }
    assert(
      m.tensors.every((t) => tids.has(t.tensor)) &&
        m.aliases.every((a) => tids.has(a.source) && tids.has(a.output)),
      "Invalid memory tensor reference",
    );
  }
  if (d.preparedParameters)
    assert(
      Array.isArray(d.preparedParameters.nodes) &&
        d.preparedParameters.nodes.every(
          (p) =>
            nids.has(String(p.node)) &&
            p.integers &&
            typeof p.integers === "object",
        ),
      "Invalid prepared parameters",
    );
  assert(
    d.capabilities &&
      typeof d.capabilities.compiler === "boolean" &&
      d.capabilities.compiler === !!d.compilerUnits.length &&
      typeof d.capabilities.loops === "boolean" &&
      d.capabilities.staticInstructions ===
        Object.keys(d.instructions).length &&
      d.capabilities.sourceMappedInstructions ===
        Object.values(d.instructions).filter((i) =>
          i.frames.some((f) => f.file),
        ).length,
    "Invalid capability or mapping coverage",
  );
  if (d.measurementSummary) {
    assert(
      d.measurementSummary.inference && d.measurementSummary.footprint,
      "Missing metric collections",
    );
    for (const m of Object.values({
      ...d.measurementSummary.inference,
      ...d.measurementSummary.footprint,
    }))
      assert(
        m &&
          typeof m.unit === "string" &&
          typeof m.scope === "string" &&
          ["measured", "derived", "unavailable"].includes(m.evidence) &&
          (m.value === null
            ? m.evidence === "unavailable"
            : m.evidence !== "unavailable" &&
              (typeof m.value === "string"
                ? uint(m.value)
                : uint(m.value.numerator) &&
                  uint(m.value.denominator) &&
                  BigInt(m.value.denominator) > 0n)),
        "Invalid scoped metric",
      );
  }
  const edgeIds = new Set<string>();
  for (const edge of d.graph.edges) {
    assert(!edgeIds.has(edge.id), "Duplicate edge");
    edgeIds.add(edge.id);
    const t = d.graph.tensors.find((t) => t.id === edge.tensorId);
    assert(
      nids.has(edge.source) &&
        nids.has(edge.target) &&
        t?.producer === edge.source &&
        t.consumers.includes(edge.target),
      "Invalid tensor edge",
    );
  }
  if (d.compilerUnits.length) {
    const c = d.compilerEvidence;
    assert(
      c?.loadableIdentical === true &&
        c.measuredElfHash === d.provenance.hashes.profile_elf &&
        safePath(c.commandInventoryPath) &&
        own(files, c.commandInventoryPath),
      "Unverified compiler evidence",
    );
  }
  const artifacts = d.compilerUnits.flatMap((u) => u.artifacts);
  for (const a of d.executionPlan.artifacts || [])
    assert(
      safePath(a.archivePath) &&
        own(files, a.archivePath) &&
        typeof a.sha256 === "string",
      "Invalid supporting artifact",
    );
  for (const a of artifacts)
    assert(
      safePath(a.archivePath) &&
        own(files, a.archivePath) &&
        Array.isArray(a.functions) &&
        a.functions.every(
          (f) =>
            Number.isSafeInteger(f.startLine) &&
            Number.isSafeInteger(f.endLine) &&
            f.startLine > 0 &&
            f.endLine >= f.startLine,
        ),
      "Invalid compiler artifact",
    );
  if (d.registers) {
    const r = d.registers;
    assert(
      r.schemaVersion === 1 &&
        r.semantics === "before-instruction" &&
        r.elfHash === d.provenance.hashes.profile_elf,
      "Invalid register evidence identity",
    );
    assert(
      r.variables && r.locations && r.coverage,
      "Missing register evidence",
    );
    for (const [id, v] of Object.entries(r.variables)) {
      assert(
        v.id === id &&
          typeof v.name === "string" &&
          typeof v.type === "string" &&
          typeof v.function === "string" &&
          ["local", "parameter"].includes(v.kind),
        "Invalid register variable",
      );
      assert(
        v.declaration === null ||
          (sourceExists(v.declaration.file) &&
            Number.isSafeInteger(v.declaration.line) &&
            v.declaration.line > 0),
        "Invalid variable declaration",
      );
    }
    for (const [reg, locations] of Object.entries(r.locations)) {
      assert(
        /^x([0-9]|[12][0-9]|3[01])$/.test(reg) && Array.isArray(locations),
        "Invalid register name",
      );
      for (const location of locations) {
        assert(
          own(r.variables, location.variableId) &&
            uint(location.low) &&
            uint(location.high) &&
            BigInt(location.low) < BigInt(location.high),
          "Invalid register location range/reference",
        );
        assert(
          ["value", "address", "piece"].includes(location.kind) &&
            typeof location.description === "string" &&
            typeof location.expression === "string",
          "Invalid register location expression",
        );
      }
    }
    const registerName = (value: string) =>
      /^x([0-9]|[12][0-9]|3[01])$/.test(value);
    const positiveLine = (value: number) =>
      Number.isSafeInteger(value) && value > 0;
    for (const [reg, relations] of Object.entries(r.relations || {})) {
      assert(
        registerName(reg) && Array.isArray(relations),
        "Invalid register relations",
      );
      for (const relation of relations) {
        assert(
          own(r.variables, relation.variableId) &&
            uint(relation.low) &&
            uint(relation.high) &&
            BigInt(relation.low) < BigInt(relation.high),
          "Invalid register relation range/reference",
        );
        assert(
          typeof relation.offset === "string" &&
            /^-?(0|[1-9][0-9]{0,18})$/.test(relation.offset) &&
            BigInt(relation.offset) >= -9223372036854775808n &&
            BigInt(relation.offset) <= 9223372036854775807n &&
            [1, 2, 4, 8].includes(relation.bytes) &&
            typeof relation.signed === "boolean" &&
            typeof relation.expression === "string",
          "Invalid symbolic memory relation",
        );
      }
    }
    assert(
      r.roles === undefined || Array.isArray(r.roles),
      "Invalid register roles",
    );
    for (const role of r.roles || []) {
      const fn = d.functions.find((f) => f.id === role.functionId);
      const loop = fn?.cfg.loops.find((l) => l.id === role.loopId);
      assert(
        fn?.cfg.complete &&
          loop?.kind === "natural" &&
          registerName(role.register) &&
          ["pointer", "boundary"].includes(role.kind),
        "Invalid register loop role",
      );
      assert(
        pcs(role.pcs) &&
          role.pcs.length === loop.pcs.length &&
          role.pcs.every((pc) => loop.pcs.includes(pc)) &&
          pcs(role.loadPcs) &&
          pcs(role.updatePcs) &&
          role.loadPcs.every((pc) => role.pcs.includes(pc)) &&
          role.updatePcs.every((pc) => role.pcs.includes(pc)) &&
          role.pcs.includes(role.comparePc) &&
          Number.isSafeInteger(role.stride) &&
          role.stride > 0 &&
          Array.isArray(role.sourceVariableIds) &&
          role.sourceVariableIds.every((id) => own(r.variables, id)) &&
          (!role.relatedRegister || registerName(role.relatedRegister)),
        "Invalid register role evidence",
      );
      if (role.span) {
        assert(
          hasPc(role.span.definitionPc) &&
            fn.pcs.includes(role.span.definitionPc) &&
            registerName(role.span.register),
          "Invalid register span definition",
        );
        const s = role.span.source;
        if (s)
          assert(
            sourceExists(s.file) &&
              d.sources[s.file].sha256 === s.sha256 &&
              positiveLine(s.line) &&
              typeof s.name === "string",
            "Stale register span source binding",
          );
      }
    }
    for (const [pc, origins] of Object.entries(r.compilerOrigins || {})) {
      assert(
        hasPc(pc) && origins && d.compilerEvidence?.loadableIdentical,
        "Unverified compiler register origins",
      );
      for (const [reg, entries] of Object.entries(origins)) {
        assert(
          registerName(reg) && Array.isArray(entries),
          "Invalid compiler register origins",
        );
        for (const entry of entries) {
          const unit = d.compilerUnits.find((u) => u.id === entry.unitId);
          const artifact = unit?.artifacts.find(
            (a) =>
              a.archivePath === entry.artifactPath && a.stage === "Final RTL",
          );
          const assembly = unit?.artifacts.find(
            (a) =>
              a.archivePath === entry.assemblyPath &&
              a.stage === "Emitted assembly",
          );
          assert(
            artifact &&
              assembly &&
              typeof entry.name === "string" &&
              entry.matching === "unique-loop-window" &&
              positiveLine(entry.startLine) &&
              positiveLine(entry.endLine) &&
              entry.endLine >= entry.startLine &&
              positiveLine(entry.assemblyLine) &&
              artifact.functions.some(
                (f) =>
                  f.startLine <= entry.startLine && entry.endLine <= f.endLine,
              ) &&
              assembly.functions.some(
                (f) =>
                  f.startLine <= entry.assemblyLine &&
                  entry.assemblyLine <= f.endLine,
              ) &&
              d.functions.some((f) =>
                f.cfg.loops.some(
                  (l) => l.id === entry.loopId && l.pcs.includes(pc),
                ),
              ),
            "Invalid compiler register alignment/reference",
          );
        }
      }
    }
  }
  for (const a of d.annotations) {
    assert(pcs(a.pcs) && a.sourceHashes, "Invalid annotation");
    if (
      a.elfHash !== d.provenance.hashes.profile_elf ||
      Object.entries(a.sourceHashes).some(
        ([p, h]) => !sourceExists(p) || d.sources[p].sha256 !== h,
      )
    )
      a.status = "stale";
  }
  return d;
}

export async function readBundle(bytes: Uint8Array) {
  assert(
    bytes.length <= LIMITS.compressed,
    "ZIP exceeds 256 MiB compressed limit",
  );
  const files: Record<string, Uint8Array> = Object.create(null);
  let total = 0,
    entries = 0;
  const unzip = new Unzip((file) => {
    assert(safePath(file.name), "Unsafe archive path");
    assert(!own(files, file.name), "Duplicate archive entry");
    assert(++entries <= LIMITS.entries, "Too many archive entries");
    assert(
      file.originalSize === undefined || file.originalSize <= LIMITS.entry,
      "Entry exceeds 128 MiB limit",
    );
    assert(
      file.compression === 0 || file.compression === 8,
      "Unsupported ZIP compression",
    );
    files[file.name] = new Uint8Array();
    let size = 0;
    const chunks: Uint8Array[] = [];
    file.ondata = (error, chunk, final) => {
      if (error) throw error;
      size += chunk.length;
      total += chunk.length;
      assert(
        size <= LIMITS.entry && total <= LIMITS.total,
        "Archive exceeds decompressed size limits",
      );
      chunks.push(chunk);
      if (final) {
        const content = new Uint8Array(size);
        let offset = 0;
        for (const part of chunks) {
          content.set(part, offset);
          offset += part.length;
        }
        files[file.name] = content;
      }
    };
    file.start();
  });
  unzip.register(UnzipInflate);
  for (let offset = 0; offset < bytes.length; offset += 65536)
    unzip.push(
      bytes.subarray(offset, offset + 65536),
      offset + 65536 >= bytes.length,
    );
  assert(
    files["manifest.json"] && files["evidence.json"],
    "Missing bundle manifest/evidence",
  );
  const manifest = JSON.parse(strFromU8(files["manifest.json"]));
  assert(
    manifest.format === "riscv-execution-explorer" &&
      manifest.schemaVersion === 2 &&
      manifest.files,
    "Unsupported bundle format/schema",
  );
  assert(
    Object.keys(manifest.files).length === Object.keys(files).length - 1,
    "Unlisted or missing archive entries",
  );
  for (const [path, meta] of Object.entries(manifest.files) as [
    string,
    { sha256: string; size: number },
  ][]) {
    assert(
      safePath(path) && own(files, path) && files[path].length === meta.size,
      "Missing file or size mismatch",
    );
    const digest = Array.from(
      new Uint8Array(
        await crypto.subtle.digest("SHA-256", files[path].slice().buffer),
      ),
    )
      .map((x) => x.toString(16).padStart(2, "0"))
      .join("");
    assert(digest === meta.sha256, "File integrity check failed: " + path);
  }
  const evidence = validateEvidence(
    JSON.parse(strFromU8(files["evidence.json"])),
    files,
  );
  for (const s of Object.values(evidence.sources))
    if (s.archivePath)
      assert(
        s.sha256 === manifest.files[s.archivePath]?.sha256,
        "Source hash mismatch",
      );
  for (const u of evidence.compilerUnits)
    for (const a of u.artifacts)
      assert(
        a.sha256 === manifest.files[a.archivePath]?.sha256,
        "Compiler artifact hash mismatch",
      );
  for (const a of evidence.executionPlan.artifacts || [])
    assert(
      a.sha256 === manifest.files[a.archivePath]?.sha256,
      "Supporting artifact hash mismatch",
    );
  return { evidence, files };
}
