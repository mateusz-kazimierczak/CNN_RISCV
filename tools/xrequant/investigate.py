#!/usr/bin/env python3
"""Prepare isolated X2 header probes and verify their immutable measurements.

These are experiments, not new canonical kernel selections. Quoted includes in
the generated model resolve the probe headers first; the ordinary builder records
their actual dependency bytes in its content-addressed evidence. Production
headers, generated X2, extension libraries and ISA contracts remain untouched.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
VARIANTS = (
    "tile2x2",
    "dw-noinline",
    "dw-rowunroll",
    "add64",
    "dw-selective",
    "combined",
)
BASE_CAPTURE = "1f04302f3bd8362f711fa77acceafcc13c9e34946539e3dd8878639deb81cf64"
WORK = ROOT / "build/xrequant/investigation"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reference_source(name):
    """Retain the original probe recipes after production kernels evolve."""
    snapshot = (
        ROOT
        / "build/profiling/compiler"
        / BASE_CAPTURE
        / "build_evidence/manifest.json"
    )
    evidence = json.loads(snapshot.read_text())
    record = evidence["files"][name]
    source = (snapshot.parent / record["blob"]).read_bytes()
    if sha(source) != record["sha256"]:
        raise ValueError(f"reference source changed: {name}")
    return source.decode()


def overlays(variant):
    files = {}
    if variant in ("dw-noinline", "dw-rowunroll", "dw-selective", "combined"):
        s = reference_source("kernels/rv64imc/depthwise.h").replace(
            '#include "quantization_select.h"',
            '#include "kernels/rv64imc/quantization_select.h"',
        )
        if variant == "dw-noinline":
            s = s.replace(
                "static inline void pixel(",
                "__attribute__((noinline)) static void pixel(",
            )
        elif variant == "dw-rowunroll":
            s = s.replace("#pragma GCC unroll 5", "#pragma GCC unroll 1", 1)
        else:
            a = s.index("  template <bool Interior>")
            b = s.index("  static inline void run(", a)
            outlined = s[a:b].replace(
                "static inline void pixel(",
                "__attribute__((noinline)) static void pixel_outlined(",
            )
            wrapper = """  template <bool Interior>
  __attribute__((always_inline)) static inline void pixel_selected(
      const int8_t *input, const int8_t *weights, const int32_t *biases,
      const int32_t *multipliers, const int32_t *shifts, int y, int x,
      int8_t *output) {
    // Model-specific probe: the winning geometry families from the uniform test.
    if constexpr ((FilterSize == 3 && StrideHeight == 1) || Channels == 672)
      pixel_outlined<Interior>(input, weights, biases, multipliers, shifts, y, x, output);
    else
      pixel<Interior>(input, weights, biases, multipliers, shifts, y, x, output);
  }

"""
            s = (
                s[:b]
                + outlined
                + wrapper
                + s[b:]
                .replace("pixel<false>(", "pixel_selected<false>(")
                .replace("pixel<true>(", "pixel_selected<true>(")
            )
        files["kernels/rv64imc/depthwise.h"] = s
    if variant in ("add64", "combined"):
        s = reference_source("kernels/project/operators.h").replace(
            '#include "quantization.h"', '#include "kernels/project/quantization.h"'
        )
        for side, offset in (("lhs", "LhsOffset"), ("rhs", "RhsOffset")):
            s = s.replace(
                f"const int32_t scaled_{side} = Scaling::scale(",
                f"const auto scaled_{side} = Scaling::scale(",
            )
            s = s.replace(
                f"({side}[i] + {offset}) * (1 << LeftShift)",
                f"(int64_t({side}[i]) + {offset}) * (int64_t{{1}} << LeftShift)",
            )
        files["kernels/project/operators.h"] = s
        s = (
            reference_source("kernels/xrequant/requant.h")
            .replace(
                "static inline int32_t scale(int32_t x,",
                "static inline int64_t scale(int64_t x,",
            )
            .replace(
                "return int32_t(xrequant(x, requant_descriptor(m, shift, 0, 0, 0, true)));",
                "return xrequant(x, requant_descriptor(m, shift, 0, 0, 0, true));",
            )
            .replace(
                "static inline int64_t output(int32_t x,",
                "static inline int64_t output(int64_t x,",
            )
        )
        files["kernels/xrequant/requant.h"] = s
    return files


def prepare(variant):
    directory = ROOT / f"build/compiler/X2-investigate-{variant}"
    command = [
        sys.executable,
        "-m",
        "compiler",
        "generate",
        "models/efficientnet-lite0-int8.tflite",
        "--config",
        "X2",
        "--output-dir",
        str(directory),
    ]
    if variant == "tile2x2":
        command += ["--pointwise-block", "2"]
    subprocess.run(command, cwd=ROOT, check=True)
    for name, source in overlays(variant).items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    print(f"Probe prepared: {directory}")


def report():
    from compiler.build_evidence import artifact_path
    from tools.freeze_compiler_baseline import verify_files
    from tools.profile_compiler import make_summary, verify_capture
    from tools.xqmac8.analysis import classify

    verify_files(
        ROOT,
        json.loads((ROOT / "tools/compiler/baseline.json").read_text())["frozen_files"],
    )

    def load(identity):
        directory = ROOT / "build/profiling/compiler" / identity
        verified = verify_capture(directory)
        return directory, verified, make_summary(directory, verified)

    def artifact(bundle, name):
        directory, verified, _ = bundle
        return artifact_path(
            directory / "build_evidence/manifest.json", verified[1], name
        ).read_bytes()

    def metrics(bundle):
        _, v, s = bundle
        stack = Counter()
        custom = Counter()
        for pc, n in v[6]["histogram"].items():
            i = v[4][pc]
            if "(x2)" in i["operands"] and classify(i["mnemonic"]) in ("load", "store"):
                stack[classify(i["mnemonic"])] += n
            if i["mnemonic"] in ("xqmac8", "xrequant"):
                custom[i["mnemonic"]] += n
        return {
            "capture_id": s["capture_id"],
            "elf_sha256": s["elf_sha256"],
            "instructions": int(s["inference"]["instructions"]["value"]),
            "mix": {k: int(x["value"]) for k, x in s["inference"]["mix"].items()},
            "stack_pointer_memory_instructions": dict(stack),
            "custom": dict(custom),
            "code_bytes": int(s["footprint"]["executable_code"]["value"]),
            "constants_and_parameters_bytes": int(
                s["footprint"]["planned_constants_and_parameters"]["value"]
            ),
            "workspace_bytes": int(
                s["footprint"]["activation_scratch_workspace"]["value"]
            ),
            "nodes": {
                str(u["nodes"][0]): int(u["metrics"]["instructions"]["value"])
                for u in s["units"]
            },
        }

    baseline = load(BASE_CAPTURE)
    before = metrics(baseline)
    experiments = {}
    for variant in VARIANTS:
        summary = json.loads((WORK / variant / "summary.json").read_text())
        candidate = load(summary["capture_id"])
        values = metrics(candidate)
        for name in ("constants.cc", "constants.h", "prepared_ir.json"):
            if artifact(candidate, name) != artifact(baseline, name):
                raise ValueError(
                    f"probe changed data or physical memory layout: {variant}/{name}"
                )
        a, b = [
            json.loads(artifact(x, "memory_plan.json")) for x in (baseline, candidate)
        ]
        # The tile's stack-policy description changes its contract hash, while
        # every physical address, offset, alignment and extent stays identical.
        for memory in (a, b):
            memory.pop("kernel_memory_sha256")
        if a != b:
            raise ValueError(f"probe changed physical memory layout: {variant}")
        for key in ("custom", "constants_and_parameters_bytes", "workspace_bytes"):
            if values[key] != before[key]:
                raise ValueError(f"probe changed work or memory: {variant}/{key}")
        hashes = {}
        for name, source in overlays(variant).items():
            key = f"build/compiler/X2-investigate-{variant}/{name}"
            actual = candidate[1][1]["files"][key]["sha256"]
            if actual != sha(source.encode()):
                raise ValueError(
                    f"probe recipe differs from compiled dependency: {key}"
                )
            hashes[name] = actual
        values["overlays_sha256"] = hashes
        values["instructions_saved"] = before["instructions"] - values["instructions"]
        values["changed_nodes"] = {
            n: {
                "before": before["nodes"][n],
                "after": count,
                "saved": before["nodes"][n] - count,
            }
            for n, count in values.pop("nodes").items()
            if count != before["nodes"][n]
        }
        values["status"] = (
            "PASS: ordinary baseline output and two identical full retirement profiles"
        )
        experiments[variant] = values
    from compiler.build_evidence import open_build
    from tools.investigation.replay import verify_replay

    def verify_build(directory, kind):
        # These historical prototypes predate the production header policies.
        # Validate their frozen build inputs and current binary, not live source.
        _, evidence = open_build(directory / kind / "build.json")
        record = evidence["build"]
        if sha((ROOT / record["binary"]).read_bytes()) != record["binary_sha256"]:
            raise ValueError(f"historical binary changed: {kind}")
        return record

    generated = ROOT / "build/compiler/X2-investigate-combined"
    production = verify_build(generated, "rv64")
    if production["binary_sha256"] != experiments["combined"]["elf_sha256"]:
        raise ValueError("combined current ELF differs from measured ELF")
    validation = {}
    for kind in ("native", "capture", "sanitized"):
        build = verify_build(generated, kind)
        path = generated / kind / "differential.json"
        proof = json.loads(path.read_text())
        if (
            proof["status"] != "PASS"
            or len(proof["cases"]) != 8
            or proof["binary_sha256"] != build["binary_sha256"]
            or proof["complete_node_arrays_compared"]
            != (0 if kind == "native" else 510)
        ):
            raise ValueError(f"combined numerical evidence incomplete: {kind}")
        for case in proof["cases"]:
            if case["status"] != (2 if case["name"] == "zero_point" else 0):
                raise ValueError(f"unexpected reference status: {case['name']}")
            for name, expected in case["files"].items():
                if (
                    sha(
                        (
                            generated / kind / "captures" / case["name"] / name
                        ).read_bytes()
                    )
                    != expected
                ):
                    raise ValueError(
                        f"combined differential artifact changed: {kind}/{case['name']}/{name}"
                    )
        validation[kind] = {
            "status": "PASS",
            "cases": 8,
            "complete_node_arrays_compared": proof["complete_node_arrays_compared"],
            "report_sha256": sha(path.read_bytes()),
        }
    path = (
        ROOT / "build/xqmac8/X2-investigate-combined/full-random_42/verification.json"
    )
    proof = json.loads(path.read_text())
    if (
        proof["status"] != "PASS"
        or proof["full_output_bytes_compared"] != 1000
        or proof["production_binary_sha256"] != production["binary_sha256"]
    ):
        raise ValueError("combined random_42 RV64 evidence incomplete")
    validation["rv64_random_42"] = {
        "status": "PASS",
        "bytes_compared": 1000,
        "report_sha256": sha(path.read_bytes()),
    }
    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X2-investigate-replay/latest.json"
    )
    if (
        workload["nodes"] != [4, 10, 33, 37]
        or len(workload["cases"]) != 8
        or set(manifest["kinds"]) != {"native", "sanitized", "rv64"}
    ):
        raise ValueError("combined replay evidence incomplete")
    # Replay materializes the compiled overlays, not the production root headers.
    for kind in manifest["kinds"]:
        record = json.loads((replay / kind / "build.json").read_text())
        for name, expected in experiments["combined"]["overlays_sha256"].items():
            matches = [
                v
                for k, v in record["dependency_sha256"].items()
                if k.endswith("/build/compiler/X2-investigate-combined/" + name)
            ]
            if matches != [expected]:
                raise ValueError(
                    f"replay did not compile the combined overlay: {kind}/{name}"
                )
    validation["replay"] = {
        "status": "PASS",
        "nodes": workload["nodes"],
        "cases": 8,
        "fixtures": len(rows),
        "kinds": manifest["kinds"],
        "capture_id": replay.name,
    }
    output = ROOT / "results/xrequant/optimization-investigation.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "MEASURED_PROTOTYPES_NOT_PROMOTED",
                "recipe_sha256": sha(Path(__file__).read_bytes()),
                "scope": "baseline full inference; compiler header overlays in isolated generated directories",
                "baseline": before,
                "experiments": experiments,
                "combined_validation": validation,
                "limitations": [
                    "Selective outlining is tuned to this model and pinned GCC, not a general rule for all shapes.",
                    "Stack-pointer memory counts include saves/restores as well as spills.",
                    "Canonical kernel plans do not describe experimental header scheduling; promotion requires explicit compiler policy and regression gates.",
                    "Retired instructions only; hardware cycles, timing and area require CV-Wally RTL.",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare")
    command.add_argument("--variant", choices=VARIANTS, required=True)
    commands.add_parser("report")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.variant)
    else:
        report()


if __name__ == "__main__":
    main()
