#!/usr/bin/env python3
"""Export selected checkpoint ELFs and linked boundaries from verified captures."""

import argparse
import collections
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from compiler.build_evidence import digest, local_file
from profile_compiler import verify_capture


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def linked_addresses(instructions, symbols, entry):
    main, output = [next(s for s in symbols if s["name"] == name) for name in ("main", "a0_output")]
    calls, addresses = [], []
    for pc, insn in instructions.items():
        bits = insn["bits"]
        if main["address"] <= pc < main["address"] + main["size"] and bits & 0xfff == 0x0ef:
            imm = ((bits >> 31) << 20) | (((bits >> 12) & 255) << 12) | (((bits >> 20) & 1) << 11) | (((bits >> 21) & 1023) << 1)
            if pc + signed(imm, 21) == entry:
                calls.append(pc + 4)
        if output["address"] <= pc < output["address"] + output["size"] and bits & 0xfff == 0x517:
            following = instructions.get(pc + 4, {}).get("bits", 0)
            if following & 0xfffff == 0x50513:
                address = pc + signed(bits & 0xfffff000, 32) + signed(following >> 20, 12)
                addresses.append((address, {"pc": f"{pc:x}", "auipc": f"{bits:08x}", "addi": f"{following:08x}"}))
    if len(calls) != 1 or len(addresses) != 1:
        raise ValueError("ambiguous linked invocation call or output address")
    return calls[0], addresses[0]


def export(output, contract_path, configurations=("X1", "X2")):
    contract = {"schema_version": 1}
    staged = []
    for configuration, checkpoint, extension in (
        ("X1", "X1-tile2x4", "Xqmac8-v1"),
        ("X2", "X2-optimized", "Xqmac8-Xrequant-v1"),
        ("X3", "X3-selected", "Xqmac8-Xrequant-Xpostinc-v1"),
        ("X4", "X4", "Xqmac8-Xrequant-Xpostinc-Xdwmac8-v1"),
        ("X5", "X5", "Xqmac8-Xrequant-Xpostinc-Xdwmac8-v1"),
    ):
        if configuration not in configurations:
            continue
        summary = json.loads((ROOT / f"results/profiling/{checkpoint}/summary.json").read_text())
        capture = ROOT / "build/profiling/compiler" / summary["capture_id"]
        manifest, evidence, _, plan, instructions, syms, invocation, _, _ = verify_capture(capture)
        if plan.configuration != configuration or manifest["checkpoint"] != checkpoint:
            raise ValueError("wrong selected checkpoint")
        elf = local_file(capture / "build_evidence", evidence["files"][evidence["build"]["binary"]]["blob"])
        if digest(elf) != summary["elf_sha256"] or str(invocation["total"]) != summary["inference"]["instructions"]["value"]:
            raise ValueError("saved summary disagrees with verified capture")
        returned, (address, proof) = linked_addresses(instructions, syms, manifest["boundaries"]["root"])
        counts = collections.Counter()
        for pc, count in invocation["histogram"].items():
            bits = instructions[pc]["bits"]
            if bits & 127 == 11:
                mnemonic = {0: "xqmac8", 0x1000: "xrequant"}.get(bits & 0xfe007000)
                if mnemonic is None and configuration in ("X4", "X5"):
                    from tools.xdwmac8.contract import decode as decode_bank
                    mnemonic = decode_bank(bits)
                if mnemonic is None:
                    raise ValueError("unknown executed custom encoding")
                counts[mnemonic] += count
            elif bits & 127 in (0x2b, 0x7b):
                from tools.xpostinc.contract import decode
                if decode(bits) is None:
                    raise ValueError("unknown executed post-increment encoding")
                counts["xpostinc_load" if bits & 127 == 0x2b else "xpostinc_store"] += count
        expected = capture / "expected-output.bin"
        if "expected_output_sha256" in contract and contract["expected_output_sha256"] != digest(expected):
            raise ValueError("checkpoint reference outputs differ")
        contract["expected_output_sha256"] = digest(expected)
        contract[configuration] = {
            "checkpoint": checkpoint, "extension": extension,
            "capture_id": capture.name, "build_evidence_sha256": manifest["build_evidence_sha256"],
            "elf_sha256": digest(elf), "entry": f"{manifest['boundaries']['root']:x}",
            "return": f"{returned:x}", "expected_instructions": str(invocation["total"]),
            "output_address": f"{address:x}", "output_address_instructions": proof,
            "output_pointer_evidence": "Unique AUIPC/ADDI pair returning a0_output; decoded from hash-bound linked ELF.",
            "custom_instructions": {name: str(counts[name]) for name in ("xqmac8", "xrequant")},
            "pass_text": f"{configuration} EfficientNet-Lite0 inference: PASS",
        }
        if configuration in ("X3", "X4", "X5"):
            contract[configuration]["custom_instructions"].update(
                {name: str(counts[name]) for name in ("xpostinc_load", "xpostinc_store")}
            )
        if configuration in ("X4", "X5"):
            from tools.xdwmac8.contract import NAMES
            contract[configuration]["custom_instructions"].update({name: str(counts[name]) for name in NAMES})
        staged.append((elf, configuration + ".elf"))
    output.mkdir(parents=True, exist_ok=True)
    for source, name in staged + [(expected, "expected-output.bin")]:
        shutil.copyfile(source, output / name)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    print(json.dumps(contract, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/cvw/custom-inputs")
    parser.add_argument("--contract", type=Path, default=Path(__file__).with_name("custom_workloads.json"))
    parser.add_argument("--configurations", nargs="+", choices=("X1", "X2", "X3", "X4", "X5"), default=("X1", "X2"))
    args = parser.parse_args()
    export(args.output, args.contract, args.configurations)
