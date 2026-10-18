#!/usr/bin/env python3
"""Check bank-get consumers and precise faults at the existing memory interface."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tools.cvw.xdwmac8.runtime import WORK, digest, compile_program, execute, image
from tools.cvw.xdwmac8.fixtures import word, trap
from tools.cvw.xqmac8.test import envelope
from tools.xdwmac8.contract import NAMES
from tools.xpostinc.contract import encode as pi
from tools.xrequant.contract import oracle as requant


def consumers():
    counts = dict.fromkeys(NAMES, 0)
    value = 0xDEADBEEF80000001
    descriptor = 0x4000000040000000
    codes = [
        "la s0,scratch",
        f"li s1,0x{value:x}",
        f"li s2,0x{descriptor:x}",
        "sd s1,0(s0)",
    ]

    def op(name, **kw):
        codes.append(word(name, **kw))
        counts[name] += 1

    op("xdwset0", rs1=9)
    op("xdwset1", rs1=8)
    for gap in (0, 1):

        def get(pair=0):
            op(f"xdwget{pair}", rd=5)
            codes.extend(["nop"] * gap)

        get()
        codes += ["add t1,t0,zero", "bne t1,s1,fail"]
        get()
        codes += ["sd t0,8(s0)", "ld t1,8(s0)", "bne t1,s1,fail"]
        get()
        codes += [f".word {pi('xsdpi', 5, 8, 0)}", "ld t1,0(s0)", "bne t1,s1,fail"]
        get()
        codes += [".insn r 0x0b,0,0,t0,x0,x0", "li t1,-2147483647", "bne t0,t1,fail"]
        get()
        codes += [
            f".insn r 0x0b,1,0,t1,t0,s2",
            f"li t2,0x{requant(value, descriptor):x}",
            "bne t1,t2,fail",
        ]
        get()
        codes += ["bne t0,s1,fail"]
        get(1)
        codes += ["ld t1,0(t0)", "bne t1,s1,fail"]
        get(1)
        codes += [
            f".word {pi('xldpi', 6, 5, 8)}",
            "bne t1,s1,fail",
            "addi t2,s0,8",
            "bne t0,t2,fail",
        ]
    codes += ["j pass"]
    return envelope(
        "\n".join(codes)
    ) + "\n.section .data\n.balign 8\nscratch: .zero 32\n", dict(
        bank=counts, postload=2, poststore=2, qmac=2, requant=2
    )


def interrupted_get():
    code = [
        "la t0,handler",
        "csrw mtvec,t0",
        "li t0,123",
        word("xdwset0", rs1=5),
        "li t0,42",
        "li t1,128",
        "csrw mie,t1",
        "csrsi mstatus,8",
        "target:",
        word("xdwget0", rd=5),
        "li t1,123",
        "bne t0,t1,fail",
        "j pass",
        ".balign 4",
        "handler:",
        "li t1,42",
        "bne t0,t1,fail",
        "csrr t1,mcause",
        "li t2,0x8000000000000007",
        "bne t1,t2,fail",
        "csrr t1,mepc",
        "la t2,target",
        "bne t1,t2,fail",
        word("xdwget0", rd=6),
        "li t2,123",
        "bne t1,t2,fail",
        "mret",
    ]
    return envelope("\n".join(code)), dict(bank={"xdwset0": 1, "xdwget0": 2}, traps=1)


def main():
    binary = WORK / "arch_project_xdwmac8/Vxdwmac8_soc_tb"
    results = {}
    program, counts = consumers()
    elf = compile_program("get-consumers", program)
    for stall in (0, 31):
        name = "get-consumers" + ("-stalled" if stall else "")
        results[name] = execute(name, binary, elf, **counts, stall=stall)
    for kind, value, cause, tval, setup in [
        ("load", 0x00033803, 5, 0x40000000, ""),
        ("postload", pi("xldpi", 16, 6, 8), 5, 0x40000000, ""),
        ("poststore", pi("xsdpi", 5, 6, 8), 7, 0x40000000, ""),
        ("postalign", pi("xldpi", 16, 6, 8), 4, 0x40000001, "li t1,0x40000001"),
    ]:
        for younger in ("mac", "set"):
            program, counts = trap(
                value, cause=cause, tval=tval, fault_setup=setup, younger=younger
            )
            program = program.replace(
                "bne t0,t4,exit", f"bne t0,t4,exit\nli t4,{tval}\nbne t1,t4,exit", 1
            )
            name = "integration-" + kind + "-" + younger
            elf = compile_program(name, program)
            results[name] = execute(name, binary, elf, **counts, stall=31)
            if not results[name]["metrics"]["bank_flush"]:
                raise ValueError("younger bank did not reach execute before fault")
    program, counts = interrupted_get()
    elf = compile_program("irq-get", program)
    _, symbols = image(elf, 64)
    for stall in (0, 31):
        name = "irq-get" + ("-stalled" if stall else "")
        results[name] = execute(
            name, binary, elf, **counts, irq_pc=symbols["target"], stall=stall
        )
    proof = {
        "status": "PASS",
        "cases": results,
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                Path(__file__).with_name("fixtures.py"),
                Path(__file__).with_name("runtime.py"),
            )
        },
    }
    (WORK / "integration-tests.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n"
    )
    print("Bank consumer/LSU integration: PASS")


if __name__ == "__main__":
    main()
