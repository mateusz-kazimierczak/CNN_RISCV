import type { Evidence, RegisterRelation } from "./types";
import { explainSourceVariable } from "./sourceVariables";
export function memoryRelationText(
  register: string,
  relation: RegisterRelation,
): string {
  const offset = BigInt(relation.offset);
  const address =
    register +
    (offset < 0n ? ` - ${-offset}` : offset > 0n ? ` + ${offset}` : "");
  const name =
    relation.signed && relation.bytes === 1
      ? "signed_byte_at"
      : `${relation.signed ? "signed_" : ""}load${relation.bytes * 8}`;
  return `${name}(${address})`;
}
export function registerDetails(
  data: Evidence,
  register: string,
  pc: string,
  nodeId: string | null,
) {
  const valid = data.registers?.elfHash === data.provenance.hashes.profile_elf;
  const evidence = valid ? data.registers : undefined;
  const address = BigInt(pc);
  const relations = (evidence?.relations?.[register] || []).filter(
    (r) => BigInt(r.low) <= address && address < BigInt(r.high),
  );
  const roles = (evidence?.roles || []).filter(
    (r) => r.register === register && r.pcs.includes(pc),
  );
  const role = roles.length === 1 ? roles[0] : undefined;
  const nearbyRelations =
    role && !relations.length
      ? [
          ...new Map(
            (evidence?.relations?.[register] || [])
              .filter(
                (r) =>
                  role.sourceVariableIds.includes(r.variableId) &&
                  BigInt(r.high) <= address &&
                  role.pcs.some(
                    (p) =>
                      BigInt(r.low) <= BigInt(p) && BigInt(p) < BigInt(r.high),
                  ),
              )
              .sort((a, b) => (BigInt(a.high) > BigInt(b.high) ? -1 : 1))
              .map((r) => [r.variableId, r] as const)
              .reverse(),
          ).values(),
        ]
      : [];
  const origins = evidence?.compilerOrigins?.[pc]?.[register] || [];
  const ids = new Set([
    ...relations.map((r) => r.variableId),
    ...(role?.sourceVariableIds || []),
  ]);
  const variables = [
    ...new Map(
      [...ids]
        .map((id) => evidence!.variables[id])
        .filter(Boolean)
        .map((v) => [
          `${v.name}:${v.declaration?.file}:${v.declaration?.line}`,
          v,
        ]),
    ).values(),
  ];
  const source = role?.span?.source;
  const span =
    source && data.sources[source.file]?.sha256 === source.sha256
      ? explainSourceVariable(data, { ...source, nodeId })
      : null;
  const fn = data.functions.find((f) => f.pcs.includes(pc));
  const block = fn?.cfg.blocks.find((b) => b.pcs.includes(pc));
  const uses = (block?.pcs || [])
    .filter((p) =>
      data.instructions[p].operands
        .split("#")[0]
        .split(/[^A-Za-z0-9_]+/)
        .includes(register),
    )
    .slice(0, 8);
  return {
    relations,
    nearbyRelations,
    role,
    origins,
    variables,
    span,
    uses,
    hasEvidence: Boolean(
      relations.length || role || origins.length || uses.length,
    ),
  };
}
