#!/usr/bin/env python3
"""Execute Xpostinc and earlier project instructions on the pinned Wally SoC."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tools.cvw.prepare_xpostinc import prepare
from tools.cvw.xqmac8 import test as qmac_tests
from tools.xqmac8.test import assembly as qmac_assembly
from tools.xqmac8.vectors import vectors as qmac_vectors
from tools.xrequant.test import assembly, vectors

WORK = ROOT / "build/cvw/xpostinc"
OVERLAY = ROOT / "build/cvw/wally-xpostinc"
PREFIX = str(ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log=None, live=False, **kwargs):
    command = list(map(str, command))
    if live:
        with Path(log).open("w") as stream:
            result = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=kwargs.pop("timeout", 600),
                **kwargs,
            )
        text = Path(log).read_text()
        if result.returncode:
            raise RuntimeError(
                f"command failed ({result.returncode}); see {log}\n{text[-2000:]}"
            )
        return text
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 600),
        **kwargs,
    )
    if log:
        Path(log).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command[:3]}; see {log}\n{(result.stdout + result.stderr)[-2000:]}"
        )
    return result.stdout


def build(configuration, jobs):
    output = WORK / configuration
    output.mkdir(parents=True, exist_ok=True)
    sources = [OVERLAY / "src/cvw.sv", Path(__file__).with_name("soc_tb.sv")]
    sources += sorted((OVERLAY / "src").glob("*/*.sv")) + sorted(
        (OVERLAY / "src").glob("*/*/*.sv")
    )
    verilator = shutil.which("verilator")
    if not verilator:
        raise RuntimeError("Verilator is required")
    command = [
        verilator,
        "--binary",
        "--timing",
        "--assert",
        "-j",
        str(jobs),
        "-Wno-fatal",
        "--top-module",
        "xpostinc_soc_tb",
        "--Mdir",
        str(output),
        "-I" + str(OVERLAY / "config/shared"),
        "-I" + str(OVERLAY / "config" / configuration),
        *sources,
        ROOT / "tools/cvw/xqmac8/getenv.cc",
    ]
    env = dict(os.environ)
    host_compiler = shutil.which("c++")
    if sys.platform == "darwin":
        host_compiler = "/Library/Developer/CommandLineTools/usr/bin/clang++"
        sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")
        env["SDKROOT"] = (
            str(sdk) if sdk.exists() else run(["xcrun", "--show-sdk-path"]).strip()
        )
        command += ["-MAKEFLAGS", f"CXX={host_compiler} LINK={host_compiler}"]
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    inputs.update(
        {
            str(Path(__file__).relative_to(ROOT)): digest(__file__),
            str((ROOT / "tools/cvw/xqmac8/getenv.cc").relative_to(ROOT)): digest(
                ROOT / "tools/cvw/xqmac8/getenv.cc"
            ),
            "integration.json": digest(OVERLAY / "integration.json"),
            **{
                str(p.relative_to(ROOT)): digest(p)
                for p in (
                    ROOT / "tools/cvw/xqmac8/test.py",
                    ROOT / "tools/xqmac8/test.py",
                    ROOT / "tools/xqmac8/vectors.py",
                    ROOT / "tools/xrequant/test.py",
                    ROOT / "tools/xrequant/contract.py",
                    ROOT / "tools/xpostinc/test.py",
                    ROOT / "tools/xpostinc/contract.py",
                )
            },
        }
    )
    identity = {
        "inputs": inputs,
        "verilator": run([verilator, "--version"]).strip(),
        "verilator_sha256": digest(verilator),
        "command": list(map(str, command)),
        "compiler": run([host_compiler, "--version"]).splitlines()[0],
        "compiler_sha256": digest(host_compiler),
    }
    record = output / "build.json"
    binary = output / "Vxpostinc_soc_tb"
    if record.exists() and binary.exists():
        old = json.loads(record.read_text())
        if old.get("identity") == identity and old["binary_sha256"] == digest(binary):
            return binary, old
    print(f"Building full SoC: {configuration}", flush=True)
    run(command, WORK / f"{configuration}-build.log", env=env, timeout=1200)
    if any(
        digest(ROOT / name) != value
        for name, value in inputs.items()
        if name != "integration.json"
    ):
        raise ValueError("RTL changed during compilation")
    value = {"identity": identity, "binary_sha256": digest(binary)}
    record.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return binary, value


def compile_program(name, text, xlen=64):
    source, obj, elf = [WORK / (name + suffix) for suffix in (".S", ".o", ".elf")]
    source.write_text(text)
    run(
        [
            PREFIX + "as",
            f"-march=rv{xlen}imc_zicsr",
            "-mabi=" + ("lp64" if xlen == 64 else "ilp32"),
            source,
            "-o",
            obj,
        ]
    )
    run(
        [
            PREFIX + "ld",
            "-m",
            f"elf{xlen}lriscv",
            "-T",
            ROOT / "tflm/platform/rv64imc/link.ld",
            obj,
            "-o",
            elf,
        ]
    )
    return elf


def image(elf, xlen):
    data = elf.read_bytes()
    is64 = data[4] == 2
    phoff = struct.unpack_from("<Q" if is64 else "<I", data, 32 if is64 else 28)[0]
    stride, count = struct.unpack_from("<HH", data, 54 if is64 else 42)
    words = {}
    for index in range(count):
        parts = struct.unpack_from(
            "<IIQQQQQQ" if is64 else "<IIIIIIII", data, phoff + index * stride
        )
        if is64:
            kind, _, offset, address, _, size, _, _ = parts
        else:
            kind, offset, address, _, size, _, _, _ = parts
        if kind != 1:
            continue
        for i, byte in enumerate(data[offset : offset + size]):
            a = address + i - 0x80000000
            if not 0 <= a < 128 * 1024**2:
                raise ValueError("ELF outside modeled RAM")
            word, lane = divmod(a, xlen // 8)
            words[word] = words.get(word, 0) | (byte << (lane * 8))
    path = WORK / (elf.stem + f"-rv{xlen}.mem")
    path.write_text(
        "\n".join(f"@{a:x}\n{w:0{xlen // 4}x}" for a, w in sorted(words.items())) + "\n"
    )
    symbols = {
        p[2]: int(p[0], 16)
        for line in run([PREFIX + "nm", elf]).splitlines()
        if len(p := line.split()) == 3
    }
    return path, symbols


def execute(
    name,
    binary,
    elf,
    xlen=64,
    qmac=0,
    requant=0,
    postload=0,
    poststore=0,
    traps=0,
    stall=0,
    timeout=600,
):
    mem, symbols = image(elf, xlen)
    command = [
        binary,
        "+IMAGE=" + str(mem),
        f"+TOHOST={symbols['tohost']:x}",
        f"+EXPECTED_CUSTOM={qmac + requant + postload + poststore}",
        f"+EXPECTED_QMAC={qmac}",
        f"+EXPECTED_REQUANT={requant}",
        f"+EXPECTED_POSTLOAD={postload}",
        f"+EXPECTED_POSTSTORE={poststore}",
        f"+EXPECTED_TRAPS={traps}",
        f"+STALL_PERIOD={stall}",
        "+MAX_CYCLES=3000000000",
    ]
    text = run(command, WORK / (name + ".log"), timeout=timeout, live=True)
    match = re.search(r"XPOSTINC_RTL_PASS (.*)", text)
    if not match:
        raise ValueError(f"incomplete RTL test: {name}")
    metrics = {
        key: int(value)
        for key, value in re.findall(
            r"(\w+)=(\d+)",
            match[1]
            + " "
            + " ".join(
                re.findall(
                    r"(?:XPOSTINC_COVERAGE|XPOSTINC_HAZARDS|XREQUANT_COVERAGE) (.*)",
                    text,
                )
            ),
        )
    }
    print(
        f"{name}: PASS ({metrics['custom']} custom, {metrics['traps']} traps)",
        flush=True,
    )
    return {
        "status": "PASS",
        "elf": str(elf.relative_to(ROOT)),
        "elf_sha256": digest(elf),
        "simulator_sha256": digest(binary),
        "command": list(map(str, command)),
        "metrics": metrics,
        "log_sha256": digest(WORK / (name + ".log")),
    }


def envelope(body, data=""):
    return qmac_tests.envelope(body) + "\n.section .data\n.balign 64\n" + data + "\n"


def hazards():
    from tools.xpostinc.contract import encode

    code = [
        "la s0,scratch",
        "la s9,pointer",
        "li s8,0x1020304050607080",
        "sd s8,0(s0)",
        "sd s8,8(s0)",
        "sd s0,0(s9)",
    ]
    counts = {"postload": 0, "poststore": 0, "qmac": 0, "requant": 0}

    def op(name, value, base, step):
        code.append(f".word {encode(name, value, base, step)}")
        counts["poststore" if name.startswith("xs") else "postload"] += 1

    for mode in ("add", "addi", "load", "mul", "div", "csr"):
        code += ["li s7,1", "csrw mscratch,s0"]
        code += [
            {
                "add": "add t0,s0,zero",
                "addi": "addi t0,s0,0",
                "load": "ld t0,0(s9)",
                "mul": "mul t0,s0,s7",
                "div": "divu t0,s0,s7",
                "csr": "csrr t0,mscratch",
            }[mode]
        ]
        op("xldpi", 6, 5, 8)
        op("xldpi", 7, 5, 8)
        code += ["addi a2,s0,16", "bne t0,a2,fail", "bne t1,s8,fail", "bne t2,s8,fail"]
        code += ["addi t1,s0,32", "csrw mscratch,s8", "sd s8,8(s9)"]
        code += [
            {
                "add": "add t0,s8,zero",
                "addi": "addi t0,s8,0",
                "load": "ld t0,8(s9)",
                "mul": "mul t0,s8,s7",
                "div": "divu t0,s8,s7",
                "csr": "csrr t0,mscratch",
            }[mode]
        ]
        op("xsdpi", 5, 6, 8)
        code += ["ld a3,-8(t1)", "bne a3,s8,fail", "addi a2,s0,40", "bne t1,a2,fail"]
    # Both results consumed simultaneously; primary load hazard must stall once.
    code += ["mv t0,s0"]
    op("xldpi", 6, 5, 8)
    code += ["add t2,t0,t1", "add a2,s0,s8", "addi a2,a2,8", "bne t2,a2,fail"]
    # Updated base forwarded to each source class, from M and W.
    for gap in (0, 1):
        code += ["mv t0,s0", "addi t2,s0,48"]
        op("xldpi", 0, 5, 8)
        code += ["nop"] * gap
        code += ["add a1,zero,t0", "addi a2,s0,8", "bne a1,a2,fail"]
        code += ["mv t0,s0"]
        op("xldpi", 0, 5, 8)
        code += ["nop"] * gap
        op("xsdpi", 5, 7, 0)  # store value uses the updated base
        code += ["ld a1,0(t2)", "addi a2,s0,8", "bne a1,a2,fail"]
        code += ["mv t0,s0"]
        op("xldpi", 0, 5, 8)
        code += ["nop"] * gap
        code += [".word 0x0000028b"]  # Xqmac8 t0,x0,x0: implicit accumulator
        counts["qmac"] += 1
        code += ["addi a2,s0,8", "addiw a2,a2,0", "bne t0,a2,fail"]
        code += ["mv t0,s0", "li s5,0x4000000040000000"]
        op("xldpi", 0, 5, 8)
        code += ["nop"] * gap
        code += [".insn r 0x0b,1,0,t1,t0,s5"]
        counts["requant"] += 1
        code += [
            "addi a2,s0,8",
            "addiw a2,a2,0",
            "addi a2,a2,1",
            "srai a2,a2,1",
            "bne t1,a2,fail",
        ]
    # Younger primary M must win over older base W, and the reverse pairing.
    code += ["mv t0,s0"]
    op("xldpi", 6, 5, 8)
    code += [
        "addi t0,s0,16",
        "add t2,t0,zero",
        "addi a2,s0,16",
        "bne t2,a2,fail",
        "addi t0,s0,0",
    ]
    op("xldpi", 6, 5, 8)
    code += ["add t2,t0,zero", "addi a2,s0,8", "bne t2,a2,fail"]
    # Randomized source/base/destination aliases across the integer register file.
    rng = random.Random(0x504F535457414C4C)
    regs = (0, 5, 6, 7, 10, 11, 12, 13, 14, 15, 28, 29, 30, 31)
    for _ in range(512):
        store = bool(rng.getrandbits(1))
        base = rng.choice(regs[1:])
        value = rng.choice(regs)
        if not store and base == value:
            value = 0
        step = rng.choice((-8, 0, 8))
        raw = rng.getrandbits(64)
        code += [f"li s8,0x{raw:016x}", "sd s8,16(s0)"]
        if value:
            code += [f"li x{value},0x{raw:016x}"]
        code += [f"addi x{base},s0,16"]
        op("xsdpi" if store else "xldpi", value, base, step)
        code += [f"addi s1,s0,{16 + step}", f"bne x{base},s1,fail"]
        if store:
            code += ["ld s2,16(s0)"]
            expected = "s8" if value else "zero"
            if value == base:
                code += ["addi s3,s0,16"]
                expected = "s3"
            code += [f"bne s2,{expected},fail"]
        elif value:
            code += [f"bne x{value},s8,fail"]
    # Taken branches flush younger loads/stores, including an invalid address.
    code += ["li s8,0x1020304050607080", "sd s8,0(s0)"]
    for index in range(32):
        code += [
            "la t0,scratch",
            "li t1,0x40000000",
            "li t2,123",
            f"beq zero,zero,skip{index}",
            f".word {encode('xsdpi', 7, 5, 8)}",
            f".word {encode('xldpi', 7, 6, 8)}",
            f"skip{index}:",
            "la s1,scratch",
            "bne t0,s1,fail",
            "ld s2,0(s1)",
            "bne s2,s8,fail",
            "li s1,0x40000000",
            "bne t1,s1,fail",
        ]
    return envelope(
        "\n".join(code), "scratch: .zero 128\n.balign 8\npointer: .zero 16"
    ), counts


def vm_program(word, cause=None, misaligned=False):
    # Data accesses use Sv39 via MPRV; instructions continue executing in M mode.
    # Identity-map the test RAM with a 2 MiB leaf and leave VA 0x40000000 unmapped.
    setup = """la s0,root
la s1,leaf
srli s2,s1,12
slli s2,s2,10
ori s2,s2,1
sd s2,16(s0)
li s2,0x200000cf
sd s2,0(s1)
li s2,-1
srli s2,s2,2
csrw pmpaddr0,s2
li s2,0x1f
csrw pmpcfg0,s2
srli s0,s0,12
li s2,0x8000000000000000
or s0,s0,s2
csrw satp,s0
sfence.vma
li s2,0x1800
csrc mstatus,s2
li s2,0x20000
li s3,0x800
or s2,s2,s3
csrs mstatus,s2
"""
    if cause is None:
        from tools.xpostinc.contract import encode

        body = (
            """la t1,scratch
li t0,0x12345678
sd t0,0(t1)
"""
            + setup
            + f""".word {encode("xldpi", 5, 6, 8)}
li a2,0x12345678
bne t0,a2,fail
la a2,scratch
addi a2,a2,8
bne t1,a2,fail
li s2,0x20000
csrc mstatus,s2
"""
        )
        return envelope(
            body, ".balign 4096\nroot: .zero 4096\nleaf: .zero 4096\nscratch: .zero 64"
        )
    from tools.xpostinc.test import trap_program

    source = trap_program(word, cause, "unmapped")
    source = source.replace(
        f"fault: .word {word}",
        setup
        + ("addi t1,t1,1\nmv a3,t1\n" if misaligned else "")
        + f"fault: .word {word}",
    )
    if misaligned:
        source = source.replace("li a2,0x40000000", "li a2,0x40000001")
    return (
        source + "\n.section .data\n.balign 4096\nroot: .zero 4096\nleaf: .zero 4096\n"
    )


def fault_program(word, cause, address, producer=None):
    """Also prove that a younger store and its base update are squashed."""
    from tools.xpostinc.contract import encode
    from tools.xpostinc.test import trap_program

    source = trap_program(word, cause, address)
    setup = "la s4,scratch\naddi s4,s4,16\nli s5,99\nsd s5,0(s4)\n"
    if producer:
        setup += (
            "li s6,0x40000000\nli s7,1\ncsrw mscratch,s6\nla s8,scratch\nsd s6,8(s8)\n"
        )
        setup += {
            "add": "add t1,s6,zero\n",
            "load": "ld t1,8(s8)\n",
            "mul": "mul t1,s6,s7\n",
            "div": "divu t1,s6,s7\n",
            "csr": "csrr t1,mscratch\n",
        }[producer]
    source = source.replace(
        f"fault: .word {word}",
        setup + f"fault: .word {word}\n.word {encode('xsdpi', 0, 20, 8)}",
    )
    check = (
        "la a2,scratch\naddi a2,a2,16\nbne s4,a2,exit\nld a1,0(a2)\nbne a1,s5,exit\n"
    )
    return source.replace("li a0,1\nexit:", check + "li a0,1\nexit:")


def ordinary_misaligned():
    # Cross a cache-line boundary with ordinary load/store when Zicclsm is on.
    return envelope(
        """la t0,scratch
li t1,0x123456789abcdef
sd t1,63(t0)
ld t2,63(t0)
bne t1,t2,fail
lbu t2,62(t0)
bnez t2,fail
lbu t2,71(t0)
bnez t2,fail
""",
        "scratch: .zero 128",
    )


def compiler_replay(pointer, enabled):
    from tools.investigation.replay import verify_replay

    directory, _manifest, workload, rows = verify_replay(pointer)
    if workload["configuration"] != "X3":
        raise ValueError("requires verified X3 replay")
    counts = {name: 0 for name in ("qmac", "requant", "postload", "poststore")}
    counts["qmac"] = sum(
        f.get("expected_xqmac8_instructions", 0) for f in workload["fixtures"]
    )
    counts["requant"] = sum(
        f.get("expected_xrequant_instructions", 0) for f in workload["fixtures"]
    )
    for row in rows:
        for name, kind in (("postload", "load"), ("poststore", "store")):
            counts[name] += int(
                row["unit"].get("postincrement", {}).get(kind, {}).get("value", 0)
            )
    kernel = (
        directory / json.loads((directory / "rv64/build.json").read_text())["binary"]
    )
    result = execute("compiler-kernel-replay", enabled, kernel, **counts, timeout=7200)
    text = (WORK / "compiler-kernel-replay.log").read_text()
    compared = [
        json.loads(line) for line in text.splitlines() if line.startswith('{"fixture":')
    ]
    if len(compared) != len(rows) or "compiler replay: PASS" not in text:
        raise ValueError("incomplete replay")
    for index, (actual, fixture) in enumerate(zip(compared, workload["fixtures"])):
        if actual != {
            "fixture": index,
            "status": fixture["expected_status"],
            "guards": True,
            "bytes_compared": fixture["output"]["bytes"],
            "first_difference": None,
        }:
            raise ValueError(f"replay mismatch: {index}")
    return result, {
        "artifact_id": directory.name,
        "fixtures": len(rows),
        "nodes": workload["nodes"],
        "cases": workload["cases"],
        "complete_output_bytes_compared": sum(r["bytes_compared"] for r in compared),
        "elf_sha256": digest(kernel),
        "counts": counts,
    }


def main():
    from tools.cvw.xrequant import test as req_tests
    from tools.xpostinc.contract import LOADS, STORES, encode
    from tools.xpostinc.test import trap_program, vector_program

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--compiler-replay", type=Path)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    integration = prepare(ROOT / ".deps/cvw", OVERLAY)
    built = {name: build(name, args.jobs) for name in integration["configurations"]}
    enabled = built["arch_project_xpostinc"][0]
    program, cases, total = vector_program()
    exported = WORK / "vectors.json"
    exported.write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x504f5354494e43", "cases": cases},
            indent=2,
        )
        + "\n"
    )
    loads = sum(c["name"] in LOADS for c in cases) + 8
    counts = {"postload": loads, "poststore": total - loads}
    results = {}
    elf = compile_program("vectors", program)
    for config in ("arch_project_xpostinc", "arch_project_xpostinc_only"):
        for stall in (0, 31):
            name = config + "-vectors" + ("-stalled" if stall else "")
            results[name] = execute(name, built[config][0], elf, **counts, stall=stall)
    program, hazard_counts = hazards()
    elf = compile_program("hazards", program)
    for stall in (0, 31):
        name = "hazards" + ("-stalled" if stall else "")
        results[name] = execute(name, enabled, elf, **hazard_counts, stall=stall)
        for gate in (
            "base_a_m",
            "base_a_w",
            "base_b_m",
            "base_b_w",
            "base_c_m",
            "base_c_w",
        ):
            if not results[name]["metrics"][gate]:
                raise ValueError(f"hazard coverage missing: {gate}")
    faults = []
    for op in (*LOADS, *STORES):
        width = 1 << ((LOADS if op in LOADS else STORES).index(op) & 3)
        faults.append(
            (op + "-access", encode(op, 5, 6, 8), 5 if op in LOADS else 7, "unmapped")
        )
        if width > 1:
            faults.append(
                (
                    op + "-misaligned",
                    encode(op, 5, 6, 8),
                    4 if op in LOADS else 6,
                    "misaligned",
                )
            )
    faults += [(op + "-alias", encode(op, 6, 6, 8), 2, "scratch") for op in LOADS]
    faults += [("reserved-load", 0x702B | (5 << 7) | (6 << 15), 2, "scratch")]
    faults += [
        (f"reserved-store-{f}", 0x7B | (f << 12) | (5 << 7) | (6 << 15), 2, "scratch")
        for f in range(4, 8)
    ]
    faults += [
        ("x0-load-fault", encode("xldpi", 0, 6, 8), 5, "unmapped"),
        ("x0-base-fault", encode("xlbpi", 5, 0, 8), 5, "zero"),
        ("x0-store-base-fault", encode("xsdpi", 5, 0, 8), 7, "zero"),
        ("alias-priority", encode("xldpi", 6, 6, 8), 2, "misaligned"),
    ]
    for label, word, cause, address in faults:
        elf = compile_program(label, fault_program(word, cause, address))
        for stall in (0, 31):
            name = label + ("-stalled" if stall else "")
            results[name] = execute(name, enabled, elf, traps=1, stall=stall)
        if "misaligned" in label:
            name = "alignment-enabled-" + label
            results[name] = execute(
                name,
                built["arch_project_xpostinc_misaligned"][0],
                elf,
                traps=1,
                stall=31,
            )
    for producer in ("add", "load", "mul", "div", "csr"):
        for op, cause in (("xldpi", 5), ("xsdpi", 7)):
            name = "fault-producer-" + producer + "-" + op
            elf = compile_program(
                name, fault_program(encode(op, 5, 6, 8), cause, "unmapped", producer)
            )
            results[name] = execute(name, enabled, elf, traps=1, stall=31)
    elf = compile_program("ordinary-misaligned", ordinary_misaligned())
    results["ordinary-misaligned"] = execute(
        "ordinary-misaligned",
        built["arch_project_xpostinc_misaligned"][0],
        elf,
        stall=31,
    )
    # Independent enables: either earlier custom instruction is illegal in PI-only mode.
    for word in (0x0073028B, 0x0073128B):
        name = f"postinc-only-illegal-{word:08x}"
        elf = compile_program(name, qmac_tests.illegal([word]))
        results[name] = execute(
            name, built["arch_project_xpostinc_only"][0], elf, traps=1
        )
    for config in ("arch_project_xpostinc_off", "arch_project_xpostinc_rv32"):
        xlen = 32 if config.endswith("rv32") else 64
        for op in (*LOADS, *STORES):
            name = config + "-" + op
            elf = compile_program(
                name, trap_program(encode(op, 5, 6, 8), 2, rv32=xlen == 32), xlen
            )
            results[name] = execute(name, built[config][0], elf, xlen, traps=1)
    # Virtual-memory tests include successful load/dual writeback after a TLB miss.
    vm = built["arch_project_xpostinc_vm"][0]
    elf = compile_program("vm-success", vm_program(0))
    results["vm-success"] = execute("vm-success", vm, elf, postload=1)
    for op in (*LOADS, *STORES):
        name = "vm-page-fault-" + op
        elf = compile_program(
            name, vm_program(encode(op, 5, 6, 8), 13 if op in LOADS else 15)
        )
        results[name] = execute(name, vm, elf, traps=1, stall=31)
    for op, cause in (("xldpi", 4), ("xsdpi", 6)):
        name = "vm-alignment-priority-" + op
        elf = compile_program(name, vm_program(encode(op, 5, 6, 8), cause, True))
        results[name] = execute(name, vm, elf, traps=1, stall=31)
    for config, (binary, _) in built.items():
        xlen = 32 if config.endswith("rv32") else 64
        elf = compile_program(
            config + "-base", qmac_tests.compatibility(xlen, True), xlen
        )
        results[config + "-base"] = execute(config + "-base", binary, elf, xlen)
    # Preserve both earlier instruction contracts on the combined overlay.
    elf = compile_program("qmac-regression", qmac_assembly(qmac_vectors()))
    results["qmac-regression"] = execute(
        "qmac-regression", enabled, elf, qmac=len(qmac_vectors())
    )
    elf = compile_program("requant-regression", assembly(vectors()))
    results["requant-regression"] = execute(
        "requant-regression", enabled, elf, requant=len(vectors()) + 64
    )
    program, count = qmac_tests.hazards()
    elf = compile_program("qmac-hazards", program)
    results["qmac-hazards"] = execute(
        "qmac-hazards", enabled, elf, qmac=count, stall=31
    )
    program, counts = req_tests.hazards()
    elf = compile_program("requant-hazards", program)
    results["requant-hazards"] = execute(
        "requant-hazards", enabled, elf, **counts, stall=31
    )
    # Isolated byte-copy loops use exactly the Spike-tested linked ELF.
    micro = ROOT / "build/xpostinc/microbenchmark/copy.elf"
    results["copy-microbenchmark"] = execute(
        "copy-microbenchmark", enabled, micro, postload=1024, poststore=1024
    )
    replay = None
    if args.compiler_replay:
        results["compiler-kernel-replay"], replay = compiler_replay(
            args.compiler_replay, enabled
        )
    for name, expected in integration["files_sha256"].items():
        if digest(OVERLAY / name) != expected:
            raise ValueError(f"overlay changed during tests: {name}")
    record = {
        "schema_version": 1,
        "status": "PASS",
        "integration": integration,
        "vectors": len(cases),
        "vector_retirements": total,
        "vectors_sha256": digest(exported),
        "faults": len(faults),
        "hazard_counts": hazard_counts,
        "builds": {k: v[1] for k, v in built.items()},
        "cases": results,
        "compiler_replay": replay,
        "scope": "functional RTL on actual Wally SoC; test-program cycles include setup/checks; physical timing/area unmeasured",
    }
    path = ROOT / "results/cvw/xpostinc/verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
