#!/usr/bin/env python3
"""Capture and analyze reproducible, simulator-side EfficientNet B0 profiles."""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/profiling/B0"
RESULTS = ROOT / "results/profiling/B0"
TOOLCHAIN = ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-"
MODEL = ROOT / "models/efficientnet-lite0-int8.tflite"
CALLBACKS = {
    "ADD": "tflite::AddEval(TfLiteContext*, TfLiteNode*)",
    "CONV_2D": "tflite::(anonymous namespace)::ConvEval(TfLiteContext*, TfLiteNode*)",
    "DEPTHWISE_CONV_2D": "tflite::(anonymous namespace)::DepthwiseConvEval(TfLiteContext*, TfLiteNode*)",
    "FULLY_CONNECTED": "tflite::(anonymous namespace)::FullyConnectedEval(TfLiteContext*, TfLiteNode*)",
    "AVERAGE_POOL_2D": "tflite::(anonymous namespace)::AverageEval(TfLiteContext*, TfLiteNode*)",
    "QUANTIZE": "tflite::EvalQuantizeReference(TfLiteContext*, TfLiteNode*)",
    "RESHAPE": "tflite::(anonymous namespace)::EvalReshapeReference(TfLiteContext*, TfLiteNode*)",
    "SOFTMAX": "tflite::(anonymous namespace)::SoftmaxEval(TfLiteContext*, TfLiteNode*)",
}
CATEGORIES = (
    "load",
    "store",
    "integer_alu",
    "multiply",
    "divide_remainder",
    "conditional_branch",
    "jump",
    "other",
    "custom",
)
MNEMONICS = {
    "load": "lb lbu lh lhu lw lwu ld c.lw c.ld c.lwsp c.ldsp",
    "store": "sb sh sw sd c.sw c.sd c.swsp c.sdsp",
    "multiply": "mul mulh mulhsu mulhu mulw",
    "divide_remainder": "div divu rem remu divw divuw remw remuw",
    "conditional_branch": "beq bne blt bge bltu bgeu c.beqz c.bnez",
    "jump": "jal jalr c.j c.jr c.jalr",
    "integer_alu": "lui auipc addi slti sltiu xori ori andi slli srli srai add sub sll slt sltu xor srl sra or and addiw slliw srliw sraiw addw subw sllw srlw sraw c.addi4spn c.nop c.addi c.addiw c.li c.addi16sp c.lui c.srli c.srai c.andi c.sub c.xor c.or c.and c.subw c.addw c.slli c.mv c.add",
    "other": "fence fence.i ecall ebreak c.ebreak csrrw csrrs csrrc csrrwi csrrsi csrrci mret sret wfi",
}
CLASSIFICATION = {
    mnemonic: category
    for category, names in MNEMONICS.items()
    for mnemonic in names.split()
}
EXPECTED_OUTPUT = (
    "TFLM EfficientNet-Lite0 inference: PASS",
    "arena_used_bytes=1688176",
    "output_top_index=21 output_top_score=48 output_sum=215",
    "output_fnv1a=0x4b6a91e2",
)


def capture(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def tool(name: str) -> str:
    return str(TOOLCHAIN) + name


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(mnemonic: str) -> str:
    if mnemonic not in CLASSIFICATION:
        raise ValueError(f"unclassified instruction: {mnemonic}")
    return CLASSIFICATION[mnemonic]


class Elf:
    """Minimal ELF64 little-endian reader: no optional reporting dependencies."""

    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        if self.data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("expected little-endian ELF64")
        header = struct.unpack_from("<16sHHIQQQIHHHHHH", self.data)
        if header[2] != 243:
            raise ValueError("expected RISC-V ELF")
        shoff, shsize, shnum, stridx = header[6], header[11], header[12], header[13]
        headers = [
            struct.unpack_from("<IIQQQQIIQQ", self.data, shoff + i * shsize)
            for i in range(shnum)
        ]
        strings = headers[stridx]
        names = self.data[strings[4] : strings[4] + strings[5]]
        self.sections = {}
        for h in headers:
            name = names[h[0] :].split(b"\0", 1)[0].decode()
            self.sections[name] = {
                "type": h[1],
                "flags": h[2],
                "address": h[3],
                "size": h[5],
                "bytes": b"" if h[1] == 8 else self.data[h[4] : h[4] + h[5]],
            }
        self.loads = []
        for i in range(header[10]):
            h = struct.unpack_from("<IIQQQQQQ", self.data, header[5] + i * header[9])
            if h[0] == 1:
                self.loads.append((h[1], *h[3:], self.data[h[2] : h[2] + h[5]]))

    def allocated(self):
        return {name: info for name, info in self.sections.items() if info["flags"] & 2}


def validate_elf(baseline: Path, profile: Path):
    a, b = Elf(baseline), Elf(profile)
    if a.allocated() != b.allocated() or a.loads != b.loads:
        raise ValueError(
            "profiling ELF changes loadable bytes, addresses, or memory layout"
        )
    if ".debug_info" not in b.sections:
        raise ValueError("profiling ELF missing debug information")
    subprocess.run(
        [
            "python3",
            str(ROOT / "tools/audit_rv64_elf.py"),
            "--readelf",
            tool("readelf"),
            "--objdump",
            tool("objdump"),
            str(profile),
        ],
        check=True,
    )


def symbols(elf: Path) -> list[dict]:
    result = []
    for line in capture(
        tool("nm"), "-S", "-n", "-C", "--defined-only", str(elf)
    ).splitlines():
        match = re.match(r"([0-9a-f]+) ([0-9a-f]+) (\S) (.*)", line)
        if match:
            address, size, kind, name = match.groups()
            result.append(
                {
                    "address": int(address, 16),
                    "size": int(size, 16),
                    "kind": kind,
                    "name": name,
                }
            )
    return result


def unique_symbol(symbol_list: list[dict], name: str) -> int:
    found = {s["address"] for s in symbol_list if s["name"] == name}
    if len(found) != 1:
        raise ValueError(f"expected one ELF entry for {name}, found {found}")
    return found.pop()


def disassemble(elf: Path) -> dict[int, dict]:
    result = {}
    for line in capture(
        tool("objdump"), "-d", "-M", "no-aliases,numeric", str(elf)
    ).splitlines():
        match = re.match(
            r"\s*([0-9a-f]+):\s+([0-9a-f]{4}|[0-9a-f]{8})\s+(\S+)(.*)", line
        )
        if match:
            pc, bits, mnemonic, operands = match.groups()
            result[int(pc, 16)] = {
                "bits": int(bits, 16),
                "length": len(bits) // 2,
                "mnemonic": mnemonic,
                "operands": operands.strip(),
            }
    return result


def valid_axis_products(
    input_size: int,
    output_size: int,
    kernel: int,
    stride: int,
    dilation: int,
    same: bool,
) -> int:
    effective = (kernel - 1) * dilation + 1
    pad = (
        max(0, (output_size - 1) * stride + effective - input_size) // 2 if same else 0
    )
    return sum(
        0 <= out * stride - pad + k * dilation < input_size
        for out in range(output_size)
        for k in range(kernel)
    )


def graph_nodes(path: Path) -> list[dict]:
    # Only capture needs FlatBuffer bindings; offline report uses saved metadata.
    import tflite

    model = tflite.Model.GetRootAsModel(path.read_bytes(), 0)
    if model.SubgraphsLength() != 1:
        raise ValueError("collector supports one fixed subgraph")
    graph = model.Subgraphs(0)
    enum = {
        getattr(tflite.BuiltinOperator, n): n
        for n in dir(tflite.BuiltinOperator)
        if n.isupper()
    }
    nodes = []
    for index in range(graph.OperatorsLength()):
        op = graph.Operators(index)
        name = enum[model.OperatorCodes(op.OpcodeIndex()).BuiltinCode()]
        inputs, outputs = (
            [int(i) for i in op.InputsAsNumpy() if i >= 0],
            [int(i) for i in op.OutputsAsNumpy()],
        )

        def shape(i):
            return [int(n) for n in graph.Tensors(i).ShapeAsNumpy()]

        node = {
            "index": index,
            "type": name,
            "group": name,
            "input_shapes": [shape(i) for i in inputs],
            "output_shapes": [shape(i) for i in outputs],
            "logical_macs": 0,
            "executed_products": 0,
        }
        if name in {"CONV_2D", "DEPTHWISE_CONV_2D"}:
            a, w, out = shape(inputs[0]), shape(inputs[1]), shape(outputs[0])
            options = (
                tflite.Conv2DOptions()
                if name == "CONV_2D"
                else tflite.DepthwiseConv2DOptions()
            )
            opts = op.BuiltinOptions()
            options.Init(opts.Bytes, opts.Pos)
            kh, kw = w[1:3]
            same = options.Padding() == tflite.Padding.SAME
            sy, sx = options.StrideH(), options.StrideW()
            dy, dx = options.DilationHFactor(), options.DilationWFactor()
            channels = out[3] * (w[3] if name == "CONV_2D" else 1)
            node["logical_macs"] = out[0] * out[1] * out[2] * channels * kh * kw
            node["executed_products"] = (
                out[0]
                * channels
                * valid_axis_products(a[1], out[1], kh, sy, dy, same)
                * valid_axis_products(a[2], out[2], kw, sx, dx, same)
            )
            node["group"] = (
                ("conv_1x1" if kh == kw == 1 else "stem_convolution")
                if name == "CONV_2D"
                else f"depthwise_{kh}x{kw}"
            )
            node["convolution"] = {
                "kernel": [kh, kw],
                "stride": [sy, sx],
                "dilation": [dy, dx],
                "padding": "SAME" if same else "VALID",
            }
        elif name == "FULLY_CONNECTED":
            out, weights = shape(outputs[0]), shape(inputs[1])
            node["logical_macs"] = math.prod(out) * weights[-1]
            node["executed_products"] = node["logical_macs"]
        nodes.append(node)
    if len(nodes) != 64 or set(n["type"] for n in nodes) != set(CALLBACKS):
        raise ValueError(
            "unexpected model graph; update and validate callback attribution explicitly"
        )
    if sum(n["logical_macs"] for n in nodes) != 385187552:
        raise ValueError("logical MAC estimate no longer matches audited model")
    return nodes


def config_for(elf: Path, path: Path):
    symbol_list = symbols(elf)
    section = Elf(elf).sections[".text"]
    lines = [f"code {section['address']:#x} {section['address'] + section['size']:#x}"]
    for name, symbol in (
        ("invoke", "tflite::MicroInterpreter::Invoke()"),
        ("allocate", "tflite::MicroInterpreter::AllocateTensors()"),
    ):
        lines.append(f"region {name} {unique_symbol(symbol_list, symbol):#x}")
    for name, symbol in CALLBACKS.items():
        lines.append(f"operator {name} {unique_symbol(symbol_list, symbol):#x}")
    path.write_text("\n".join(lines) + "\n")


def load_capture(prefix: Path, nodes: list[dict], instructions: dict[int, dict]):
    with Path(str(prefix) + ".events.csv").open() as f:
        events = list(csv.DictReader(f))
    for expected_id, event in enumerate(events):
        for key in (
            "event_id",
            "entry",
            "return_pc",
            "complete",
            "status",
            "total",
            "faulted",
        ):
            event[key] = int(event[key])
        if (
            event["event_id"] != expected_id
            or event["complete"] != 1
            or event["status"]
            or event["faulted"]
            or event["total"] <= 0
        ):
            raise ValueError(f"invalid/incomplete region: {event}")
        event["histogram"] = {}
        event["mix"] = dict.fromkeys(CATEGORIES, 0)
    regions = [e for e in events if e["kind"] == "region"]
    ops = [e for e in events if e["kind"] == "operator"]
    expected_sequence = [("region", "allocate"), ("region", "invoke")] + [
        ("operator", n["type"]) for n in nodes
    ]
    if [(e["kind"], e["name"]) for e in events] != expected_sequence:
        raise ValueError(
            "allocation/inference/operator event sequence does not match fixed graph"
        )
    with Path(str(prefix) + ".pcs.csv").open() as f:
        for row in csv.DictReader(f):
            event_id, pc, bits, length, count = (
                int(row[k]) for k in ("event_id", "pc", "bits", "length", "count")
            )
            if event_id < 0 or event_id >= len(events) or count <= 0:
                raise ValueError("invalid histogram row")
            event = events[event_id]
            instruction = instructions.get(pc)
            if (
                not instruction
                or (bits, length) != (instruction["bits"], instruction["length"])
                or pc in event["histogram"]
            ):
                raise ValueError(f"invalid, duplicate or undecodable PC {pc:#x}")
            event["histogram"][pc] = count
            event["mix"][classify(instruction["mnemonic"])] += count
    for event in events:
        if (
            sum(event["histogram"].values()) != event["total"]
            or sum(event["mix"].values()) != event["total"]
        ):
            raise ValueError("histogram/mix totals do not reconcile")
    allocate, invoke = regions
    residual = dict(invoke["histogram"])
    for op in ops:
        for pc, count in op["histogram"].items():
            residual[pc] = residual.get(pc, 0) - count
            if residual[pc] < 0:
                raise ValueError("operator counts exceed inference counts")
    overhead = sum(residual.values())
    if overhead + sum(op["total"] for op in ops) != invoke["total"]:
        raise ValueError("operator and overhead totals do not reconcile")
    return allocate, invoke, ops, overhead


def check_output(output: str):
    lines = output.replace("\r", "").splitlines()
    if any(lines.count(expected) != 1 for expected in EXPECTED_OUTPUT):
        raise ValueError("model output does not match native TFLM reference")


def run_profile(args):
    BUILD.mkdir(parents=True, exist_ok=True)
    validate_elf(args.baseline, args.elf)
    nodes = graph_nodes(MODEL)
    config = BUILD / "regions.txt"
    config_for(args.elf, config)
    # A successful subprocess is mandatory: do not hide Spike failures in pipes.
    reference = subprocess.run(
        [str(ROOT / ".deps/spike/bin/spike"), "--isa=rv64imc", str(args.baseline)],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    check_output(reference.stdout)
    (BUILD / "ordinary-output.txt").write_text(reference.stdout.replace("\r", ""))
    commands = []
    for repeat in (1, 2):
        prefix = BUILD / f"run{repeat}"
        command = [
            str(ROOT / ".deps/spike-profile/bin/spike"),
            "--isa=rv64imc",
            f"--profile-config={config}",
            f"--profile-output={prefix}",
            str(args.elf),
        ]
        commands.append(command)
        print(f"Collecting {args.configuration} run {repeat}/2", flush=True)
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=1800
        )
        (BUILD / f"run{repeat}-output.txt").write_text(result.stdout.replace("\r", ""))
        (BUILD / f"run{repeat}-stderr.txt").write_text(result.stderr)
        check_output(result.stdout)
    for suffix in ("events.csv", "pcs.csv"):
        if (BUILD / f"run1.{suffix}").read_bytes() != (
            BUILD / f"run2.{suffix}"
        ).read_bytes():
            raise ValueError(f"repeated captures differ: {suffix}")
    # Persist all report inputs: the offline report never needs FlatBuffer bindings.
    instruction_list = disassemble(args.elf)
    symbol_list = symbols(args.elf)
    elf = Elf(args.elf)
    model_symbol = next(
        s for s in symbol_list if s["name"] == "g_efficientnet_lite0_int8_model_data"
    )

    def rel(path):
        return str(Path(path).relative_to(ROOT))

    manifest = {
        "schema_version": 1,
        "configuration": args.configuration,
        "input_seed": 1,
        "output_fnv1a": "0x4b6a91e2",
        "repository_revision": capture(
            "git", "-C", str(ROOT), "rev-parse", "HEAD"
        ).strip(),
        "repository_dirty_status": capture(
            "git", "-C", str(ROOT), "status", "--porcelain"
        ),
        "compiler": capture(tool("g++"), "--version").splitlines()[0],
        "compiler_flags": {
            "core_optimization": "-Os",
            "kernel_optimization": "-O2",
            "build_type": "release_with_logs",
            "isa": "rv64imc",
            "abi": "lp64",
            "debug": "-g",
        },
        "tflm_revision": capture(
            "git", "-C", str(ROOT / ".deps/tflite-micro"), "rev-parse", "HEAD"
        ).strip(),
        "spike_revision": capture(
            "git", "-C", str(ROOT / ".deps/riscv-isa-sim-profile"), "rev-parse", "HEAD"
        ).strip(),
        "hashes": {
            "model": sha(MODEL),
            "baseline_elf": sha(args.baseline),
            "profile_elf": sha(args.elf),
            "spike_patch": sha(ROOT / "tools/spike_profile/spike.patch"),
            "profiler_header": sha(ROOT / "tools/spike_profile/roi_profiler.h"),
            "collector_binary": sha(ROOT / ".deps/spike-profile/bin/spike"),
            "analysis_script": sha(Path(__file__)),
        },
        "loadable_sections_identical": True,
        "repeat_histograms_identical": True,
        "capture_commands": [
            [rel(c[0]), *[v.replace(str(ROOT) + "/", "") for v in c[1:]]]
            for c in commands
        ],
        "boundaries": "function entry through return instruction inclusive; caller call excluded; callbacks include callees; setup and printing excluded from Invoke",
        "footprint": {
            "executable_code_bytes": sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 2 and s["flags"] & 4
            ),
            "model_bytes": model_symbol["size"],
            "other_readonly_bytes": sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 2 and not s["flags"] & 5
            )
            - model_symbol["size"],
            "initialized_writable_bytes": sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 3 == 3 and s["type"] != 8
            ),
            "bss_bytes": sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 2 and s["type"] == 8
            ),
        },
        "nodes": nodes,
        "symbols": symbol_list,
        "instructions": instruction_list,
    }
    flags = capture(
        "gmake",
        "-s",
        "-C",
        str(ROOT / ".deps/tflite-micro"),
        "-f",
        "tensorflow/lite/micro/tools/make/Makefile",
        "-f",
        str(ROOT / "tools/spike_profile/print_flags.mk"),
        f"EXTERNAL_DIR={ROOT}",
        "TARGET=rv64imc",
        "TARGET_ARCH=rv64imc",
        f"RV64_TOOLCHAIN_ROOT={ROOT}/.deps/xpack-riscv/bin/",
        f"PATH_TO_TARGET_SRCS={ROOT}/tflm/platform/rv64imc",
        "SKIP_DOWNLOADS=1",
        "BUILD_TYPE=release_with_logs",
        "PROFILE_DEBUG_SYMBOLS=1",
        "profile-print-flags",
    )
    manifest["resolved_build_flags"] = {
        line.split("=", 1)[0]: line.split("=", 1)[1].replace(str(ROOT) + "/", "")
        for line in flags.splitlines()
        if "=" in line
    }
    # Normalize source paths now so report regeneration is portable.
    pc_set = set()
    for suffix in ("run1.pcs.csv",):
        with (BUILD / suffix).open() as f:
            pc_set.update(int(r["pc"]) for r in csv.DictReader(f))
    pcs = sorted(pc_set)
    # addr2line can expose multiple inline frames; retain them all with address delimiters.
    source_lines = capture(
        tool("addr2line"),
        "-a",
        "-f",
        "-C",
        "-i",
        "-e",
        str(args.elf),
        *[hex(pc) for pc in pcs],
    )
    sources, current = {}, None
    for line in source_lines.splitlines():
        if re.fullmatch(r"0x[0-9a-f]+", line):
            current = int(line, 16)
            sources[current] = []
        elif current is not None:
            sources[current].append(line.replace(str(ROOT) + "/", ""))
    manifest["sources"] = sources
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report(BUILD, RESULTS)


def metrics(total: int, mix: dict, logical: int, executed: int) -> dict:
    memory = mix["load"] + mix["store"]
    return {
        "instructions": total,
        "mix": mix,
        "logical_macs": logical,
        "executed_products": executed,
        "logical_macs_per_instruction": logical / total if total else 0,
        "executed_products_per_instruction": executed / total if total else 0,
        "memory_instructions": memory,
        "memory_instructions_per_executed_product": memory / executed
        if executed
        else None,
        "custom_instruction_count": mix["custom"],
        "custom_instruction_frequency": mix["custom"] / total if total else 0,
    }


def report(build: Path, output: Path):
    manifest = json.loads((build / "manifest.json").read_text())
    instructions = {int(k): v for k, v in manifest["instructions"].items()}
    nodes = manifest["nodes"]
    for suffix in ("events.csv", "pcs.csv"):
        if (build / f"run1.{suffix}").read_bytes() != (
            build / f"run2.{suffix}"
        ).read_bytes():
            raise ValueError("repeat captures changed after collection")
    for name in ("ordinary-output.txt", "run1-output.txt", "run2-output.txt"):
        check_output((build / name).read_text())
    allocate, invoke, ops, overhead = load_capture(build / "run1", nodes, instructions)
    layers = []
    for node, op in zip(nodes, ops):
        layers.append(
            {
                **node,
                **metrics(
                    op["total"],
                    op["mix"],
                    node["logical_macs"],
                    node["executed_products"],
                ),
                "instruction_share": op["total"] / invoke["total"],
            }
        )
    groups = []
    for name in sorted({n["group"] for n in layers}):
        members = [n for n in layers if n["group"] == name]
        groups.append(
            {
                "group": name,
                "layer_count": len(members),
                **metrics(
                    sum(n["instructions"] for n in members),
                    {cat: sum(n["mix"][cat] for n in members) for cat in CATEGORIES},
                    sum(n["logical_macs"] for n in members),
                    sum(n["executed_products"] for n in members),
                ),
            }
        )
    functions = [s for s in manifest["symbols"] if s["kind"] in "tTW" and s["size"]]
    functions.sort(key=lambda s: (s["address"], s["name"]))
    starts = [s["address"] for s in functions]

    def function_at(pc):
        i = bisect.bisect_right(starts, pc) - 1
        if i < 0 or pc >= functions[i]["address"] + functions[i]["size"]:
            raise ValueError(f"missing symbol attribution for {pc:#x}")
        return functions[i]["name"]

    helper_names = {
        "tflite::MultiplyByQuantizedMultiplier(int, int, int)",
        "tflite::MultiplyByQuantizedMultiplier(long, int, int)",
    }

    def summarize(event):
        function_counts = collections.Counter()
        for pc, count in event["histogram"].items():
            function_counts[function_at(pc)] += count
        hotpcs = [
            {
                "pc": hex(pc),
                "instructions": count,
                "function": function_at(pc),
                **instructions[pc],
                "source": manifest["sources"].get(str(pc), []),
            }
            for pc, count in sorted(
                event["histogram"].items(), key=lambda p: (-p[1], p[0])
            )[:30]
        ]
        return {
            "top_functions": [
                {
                    "function": name,
                    "instructions": count,
                    "share": count / event["total"],
                }
                for name, count in function_counts.most_common(15)
            ],
            "top_pcs": hotpcs,
            "fixed_point_scaling_helper_body_instructions": sum(
                function_counts[n] for n in helper_names
            ),
        }

    for layer, op in zip(layers, ops):
        layer["fixed_point_scaling_helper_body_instructions"] = summarize(op)[
            "fixed_point_scaling_helper_body_instructions"
        ]
    logical = sum(n["logical_macs"] for n in nodes)
    executed = sum(n["executed_products"] for n in nodes)
    result = {
        "schema_version": 1,
        "configuration": manifest["configuration"],
        "provenance": {
            k: v
            for k, v in manifest.items()
            if k not in {"nodes", "symbols", "instructions", "sources"}
        },
        "inference": {
            **metrics(invoke["total"], invoke["mix"], logical, executed),
            "interpreter_overhead_instructions": overhead,
            **summarize(invoke),
        },
        "allocation": {
            **metrics(allocate["total"], allocate["mix"], 0, 0),
            **summarize(allocate),
        },
        "groups": groups,
        "layers": layers,
    }
    # Capture-time script identity is preserved; an offline report may have a
    # newer presentation/validation implementation without rerunning inference.
    result["provenance"]["report_generator_sha256"] = sha(Path(__file__))
    result["provenance"]["capture_sha256"] = {
        name: sha(build / name)
        for name in (
            "regions.txt",
            "run1.events.csv",
            "run1.pcs.csv",
            "run2.events.csv",
            "run2.pcs.csv",
        )
    }
    result["inference"]["compressed_instructions"] = sum(
        count
        for pc, count in invoke["histogram"].items()
        if instructions[pc]["length"] == 2
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    fields = [
        "index",
        "type",
        "group",
        "instructions",
        "instruction_share",
        "logical_macs",
        "executed_products",
        "logical_macs_per_instruction",
        "executed_products_per_instruction",
        "memory_instructions",
        "memory_instructions_per_executed_product",
        "fixed_point_scaling_helper_body_instructions",
        *CATEGORIES,
    ]
    with (output / "layers.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for layer in layers:
            writer.writerow({k: ({**layer, **layer["mix"]}).get(k) for k in fields})
    write_markdown(result, output / "README.md")
    print(
        f"Validated {manifest['configuration']}: {invoke['total']:,} instructions; {executed:,} executed products; overhead {overhead:,}",
        flush=True,
    )


def write_markdown(result: dict, path: Path):
    inference, allocation = result["inference"], result["allocation"]
    total = inference["instructions"]
    lines = [
        f"# {result['configuration']}: EfficientNet-Lite0 RV64IMC instruction profile",
        "",
        "Two complete captures matched exactly. The ordinary and profiling simulator produced the native reference checksum `0x4b6a91e2`; profiling and ordinary ELF loadable sections are identical.",
        "",
        f"`Invoke()`: **{total:,} retired instructions**. `AllocateTensors()`: {allocation['instructions']:,}, measured separately.",
        f"Logical MACs: {inference['logical_macs']:,}; executed products (excluding skipped padding): {inference['executed_products']:,}.",
        f"Executed products/instruction: {inference['executed_products_per_instruction']:.6f}; memory instructions/product: {inference['memory_instructions_per_executed_product']:.6f}.",
        f"Interpreter overhead: {inference['interpreter_overhead_instructions']:,} instructions. Custom instruction utilization: 0.",
        "",
        "These are ISA-level instruction measurements, **not cycle counts or timing speedups**. Memory instruction counts do not establish cache misses, stalls, or external bandwidth. Fixed-point helper counts exclude surrounding zero-point, clamp, store, and caller call instructions.",
        "",
        "## Instruction mix",
        "",
        "| Class | Retired | Share |",
        "|---|---:|---:|",
    ]
    for category, count in inference["mix"].items():
        lines.append(f"| {category} | {count:,} | {count / total:.2%} |")
    lines += [
        "",
        "## Operator groups",
        "",
        "| Group | Layers | Instructions | Inference share | Products/instruction |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in sorted(result["groups"], key=lambda g: -g["instructions"]):
        lines.append(
            f"| {group['group']} | {group['layer_count']} | {group['instructions']:,} | {group['instructions'] / total:.2%} | {group['executed_products_per_instruction']:.5f} |"
        )
    lines += [
        "",
        "## Hottest functions",
        "",
        "Counts are exclusive PC attribution: callees have their own rows; per-layer totals are inclusive.",
        "",
        "| Function | Instructions | Share |",
        "|---|---:|---:|",
    ]
    for function in inference["top_functions"][:10]:
        display_name = (
            function["function"].replace("(anonymous namespace)::", "").split("(")[0]
        )
        lines.append(
            f"| `{display_name}` | {function['instructions']:,} | {function['share']:.2%} |"
        )
    lines += [
        "",
        "## Hottest instruction PCs",
        "",
        "| PC | Instruction | Executions | Source |",
        "|---|---|---:|---|",
    ]
    for pc in inference["top_pcs"][:15]:
        source = (
            (pc["source"][-1] if pc["source"] else "unknown")
            .removeprefix(".deps/tflite-micro/")
            .replace("|", "\\|")
        )
        operands = re.sub(r"\s*(?:#|<).*$", "", pc["operands"]).strip()
        lines.append(
            f"| `{pc['pc']}` | `{pc['mnemonic']} {operands}` | {pc['instructions']:,} | {source} |"
        )
    lines += [
        "",
        "## Representative layers for the next milestone",
        "",
        "Choose the highest-instruction layer in each compute family; these are recommendations, not extracted standalone benchmarks.",
        "",
        "| Family | Node | Input / weights / output | Instructions |",
        "|---|---:|---|---:|",
    ]
    for family in (
        "conv_1x1",
        "stem_convolution",
        "depthwise_3x3",
        "depthwise_5x5",
        "FULLY_CONNECTED",
    ):
        layer = max(
            (n for n in result["layers"] if n["group"] == family),
            key=lambda n: n["instructions"],
        )
        lines.append(
            f"| {family} | {layer['index']} | `{layer['input_shapes'][:2]} -> {layer['output_shapes']}` | {layer['instructions']:,} |"
        )
    lines += [
        "",
        "## Footprint",
        "",
        "Debug information is non-loadable and excluded; BSS includes the reserved 2 MiB arena, not just its used portion.",
        "",
    ]
    lines += [
        f"- {name}: {value:,}"
        for name, value in result["provenance"]["footprint"].items()
    ]
    lines += [
        "",
        "## Interpretation and reproduction",
        "",
        "Read [analysis.md](analysis.md) for the reviewed bottleneck ranking and disassembly evidence. Run `gmake profile-tests`, then `gmake profile-spike`. Run `gmake profile-report` to regenerate reports from ignored captures. `summary.json` records provenance and per-layer results; `layers.csv` is the comparison table. See [the profiling guide](../../../docs/profiling.md) for methodology and later B1/X1/X2 comparisons.",
        "",
    ]
    path.write_text("\n".join(lines))


def main():
    global BUILD, RESULTS
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--baseline", type=Path, required=True)
    run.add_argument("--elf", type=Path, required=True)
    offline = sub.add_parser("report")
    for command in (run, offline):
        command.add_argument("--configuration", default="B0")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.configuration):
        parser.error("configuration must be a simple directory name")
    BUILD = ROOT / "build/profiling" / args.configuration
    RESULTS = ROOT / "results/profiling" / args.configuration
    if args.command == "run":
        run_profile(args)
    else:
        report(BUILD, RESULTS)


if __name__ == "__main__":
    main()
