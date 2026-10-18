#!/usr/bin/env python3
"""Compare identical byte-copy loops with ordinary and post-increment memory."""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.custom_isa import extension_identity, spike_command
from tools.xpostinc.contract import decode, encode
from tools.xpostinc.test import run
from tools.xqmac8 import test as fixtures
from tools.xqmac8.runtime import digest


def main():
    output = ROOT / "build/xpostinc/microbenchmark"
    output.mkdir(parents=True, exist_ok=True)
    fixtures.OUTPUT = output
    text = [
        ".option norvc",
        ".option norelax",
        ".section .text.init",
        ".globl _start,baseline,postinc,fixture_end",
        "_start:",
        "call baseline",
        "call postinc",
        "la t1,input",
        "la t2,plain",
        "la t3,fused",
        "li t4,1024",
        "check:",
        "lbu a0,0(t1)",
        "lbu a1,0(t2)",
        "lbu a2,0(t3)",
        "bne a0,a1,fail",
        "bne a0,a2,fail",
        "addi t1,t1,1",
        "addi t2,t2,1",
        "addi t3,t3,1",
        "addi t4,t4,-1",
        "bnez t4,check",
        "li a0,1",
        "j exit",
        "fail: li a0,3",
        "exit:",
        "la a1,tohost",
        "sd a0,0(a1)",
        "1: j 1b",
    ]
    for label, target in (("baseline", "plain"), ("postinc", "fused")):
        text += [
            label + ":",
            "la t1,input",
            f"la t2,{target}",
            "li t4,1024",
            label + "_loop:",
        ]
        if label == "baseline":
            text += ["lbu t0,0(t1)", "sb t0,0(t2)", "addi t1,t1,1", "addi t2,t2,1"]
        else:
            text += [
                f".word {encode('xlbupi', 5, 6, 1)}",
                f".word {encode('xsbpi', 5, 7, 1)}",
            ]
        text += ["addi t4,t4,-1", f"bnez t4,{label}_loop", "ret"]
    text += [
        "fixture_end:",
        ".section .data",
        ".balign 64",
        "input:",
        ".byte " + ",".join(str(i % 256) for i in range(1024)),
        "plain: .zero 1024",
        "fused: .zero 1024",
        '.section .tohost,"aw",@progbits',
        ".balign 64",
        ".globl tohost,fromhost",
        "tohost: .dword 0",
        "fromhost: .dword 0",
    ]
    elf = fixtures.compile_asm("copy", "\n".join(text) + "\n")
    run([*spike_command("X3"), elf])
    symbols = run([fixtures.PREFIX + "nm", "-n", elf]).stdout
    addr = lambda name: next(
        line.split()[0] for line in symbols.splitlines() if line.endswith(" " + name)
    )
    config = output / "regions.txt"
    config.write_text(
        f"code 0x{addr('_start')} 0x{addr('fixture_end')}\nregion baseline 0x{addr('baseline')}\nregion postinc 0x{addr('postinc')}\n"
    )
    for n in (1, 2):
        prefix = output / f"run{n}"
        run(
            [
                *spike_command("X3", "profile"),
                f"--profile-config={config}",
                f"--profile-output={prefix}",
                elf,
            ]
        )
    for suffix in (".events.csv", ".pcs.csv"):
        if (output / ("run1" + suffix)).read_bytes() != (
            output / ("run2" + suffix)
        ).read_bytes():
            raise ValueError("microbenchmark profiles differ")
    with (output / "run1.events.csv").open() as f:
        events = list(csv.DictReader(f))
    if len(events) != 2 or any(e["complete"] != "1" for e in events):
        raise ValueError("incomplete copy")
    counts = {e["name"]: int(e["total"]) for e in events}
    with (output / "run1.pcs.csv").open() as f:
        custom = sum(
            int(r["count"])
            for r in csv.DictReader(f)
            if decode(int(r["bits"]), int(r["length"]))
        )
    if counts != {"baseline": 6150, "postinc": 4102} or custom != 2048:
        raise ValueError(f"unexpected counts: {counts}, {custom}")
    report = {
        "status": "PASS",
        "bytes_compared": 2048,
        "counts": counts,
        "postincrement_instructions": custom,
        "instruction_reduction": (counts["baseline"] - counts["postinc"])
        / counts["baseline"],
        "repeated_profiles_identical": True,
        "elf_sha256": digest(elf),
        "extensions": extension_identity("profile", "X3"),
    }
    (output / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(f"Xpostinc byte-copy microbenchmark: PASS {counts}")


if __name__ == "__main__":
    main()
