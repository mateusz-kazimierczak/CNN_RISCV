"""Repeated, per-invocation kernel profiles and exact replay output validation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from profile_compiler import event_metrics, metric, uint
from profile_spike import CATEGORIES, Elf, symbols, unique_symbol
from tools.xqmac8.analysis import classify, disassemble
from tools.custom_isa import spike_command, extension_identity

from compiler.build_evidence import (
    canonical,
    digest,
    local_file,
    open_build,
    verify_snapshot,
)
from compiler.replay import make_fixtures

from .build import build_replay, prepare_sources
from .common import ROOT, run, seal, verify_archive

FORMAT = "compiler-kernel-replay"


def check_output(text, workload):
    lines = text.replace("\r", "").splitlines()
    if lines[-1:] != ["compiler replay: PASS"]:
        raise ValueError("replay did not complete")
    rows = [json.loads(line) for line in lines[:-1]]
    if len(rows) != len(workload["fixtures"]):
        raise ValueError("replay fixture coverage differs")
    for i, (row, fixture) in enumerate(zip(rows, workload["fixtures"])):
        if row != {
            "fixture": i,
            "status": fixture["expected_status"],
            "guards": True,
            "bytes_compared": fixture["output"]["bytes"],
            "first_difference": None,
        }:
            raise ValueError(
                f"{fixture['id']}: wrong status/guards/complete output bytes"
            )
    return rows


def boundaries(elf, workload):
    syms, ins = symbols(elf), disassemble(elf)
    text = Elf(elf).sections[".text"]
    root = unique_symbol(syms, "replay_invoke")
    entries = {
        f["symbol"]: unique_symbol(syms, f["symbol"]) for f in workload["fixtures"]
    }
    if (
        root in entries.values()
        or len(set(entries.values())) != len(entries)
        or any(pc not in ins for pc in [root, *entries.values()])
    ):
        raise ValueError("ambiguous or undecodable replay boundaries")
    config = [
        f"code {text['address']:#x} {text['address'] + text['size']:#x}",
        f"region invoke {root:#x}",
    ]
    config += [f"operator probe_{pc:x} {pc:#x}" for pc in sorted(entries.values())]
    return root, entries, ins, "\n".join(config) + "\n"


def load_profile(prefix, workload, root, entries, ins):
    with Path(str(prefix) + ".events.csv").open() as f:
        events = list(csv.DictReader(f))
    expected = []
    for fixture in workload["fixtures"]:
        pc = entries[fixture["symbol"]]
        expected += [
            ("region", "invoke", root, fixture["expected_status"]),
            ("operator", f"probe_{pc:x}", pc, fixture["expected_status"]),
        ]
    if len(events) != len(expected):
        raise ValueError("replay event schedule differs")
    for i, (event, (kind, name, entry, status)) in enumerate(zip(events, expected)):
        for key in (
            "event_id",
            "entry",
            "return_pc",
            "complete",
            "status",
            "total",
            "faulted",
        ):
            event[key] = uint(event[key])
        if (
            event["event_id"] != i
            or (event["kind"], event["name"], event["entry"], event["status"])
            != (kind, name, entry, status)
            or event["complete"] != 1
            or event["faulted"]
            or not event["total"]
            or event["return_pc"] not in ins
        ):
            raise ValueError("invalid/incomplete replay event")
        event["histogram"], event["mix"] = {}, dict.fromkeys(CATEGORIES, 0)
    with Path(str(prefix) + ".pcs.csv").open() as f:
        for row in csv.DictReader(f):
            eid, pc, bits, length, count = [
                uint(row[k]) for k in ("event_id", "pc", "bits", "length", "count")
            ]
            if (
                eid >= len(events)
                or not count
                or pc not in ins
                or (bits, length) != (ins[pc]["bits"], ins[pc]["length"])
                or pc in events[eid]["histogram"]
            ):
                raise ValueError("invalid or duplicate replay PC")
            event = events[eid]
            event["histogram"][pc] = count
            event["mix"][classify(ins[pc]["mnemonic"])] += count
    for event in events:
        if (
            sum(event["histogram"].values()) != event["total"]
            or not event["histogram"].get(event["entry"])
            or sum(event["mix"].values()) != event["total"]
        ):
            raise ValueError("replay histogram does not reconcile")
    result = []
    for index, fixture in enumerate(workload["fixtures"]):
        invocation, unit = events[2 * index : 2 * index + 2]
        if "expected_xqmac8_instructions" in fixture and (
            unit["mix"]["custom"]
            != (
                fixture["expected_xqmac8_instructions"]
                + fixture.get("expected_xrequant_instructions", 0)
            )
            or invocation["mix"]["custom"]
            != (
                fixture["expected_xqmac8_instructions"]
                + fixture.get("expected_xrequant_instructions", 0)
            )
        ):
            raise ValueError(
                "replay Xqmac8 count differs from executed eight-product groups"
            )
        residual = dict(invocation["histogram"])
        for pc, n in unit["histogram"].items():
            residual[pc] = residual.get(pc, 0) - n
            if residual[pc] < 0:
                raise ValueError("replay unit exceeds invocation per PC")
        if sum(residual.values()) + unit["total"] != invocation["total"]:
            raise ValueError("replay invocation partition mismatch")
        if "expected_xrequant_instructions" in fixture:
            for mnemonic, key in (
                ("xqmac8", "expected_xqmac8_instructions"),
                ("xrequant", "expected_xrequant_instructions"),
            ):
                if (
                    sum(
                        n
                        for pc, n in unit["histogram"].items()
                        if ins[pc]["mnemonic"] == mnemonic
                    )
                    != fixture[key]
                ):
                    raise ValueError("replay opcode-specific custom count mismatch")
        if "expected_xpostinc_instructions" in fixture:
            from tools.xpostinc.contract import LOADS, STORES

            for event in (invocation, unit):
                event["postincrement"] = {
                    kind: sum(
                        n
                        for pc, n in event["histogram"].items()
                        if ins[pc]["mnemonic"] in names
                    )
                    for kind, names in (("load", LOADS), ("store", STORES))
                }
                if event["postincrement"] != fixture["expected_xpostinc_instructions"]:
                    raise ValueError(
                        "replay postincrement count differs from declared schedule"
                    )
        result.append(
            {
                "fixture": fixture["id"],
                "kind": fixture["kind"],
                "node": fixture["node"],
                "symbol": fixture["symbol"],
                "input_sha256": [b["sha256"] for b in fixture["inputs"]],
                "expected_output_sha256": fixture["output"]["sha256"]
                if fixture["expected_status"] == 0
                else None,
                "status": fixture["expected_status"],
                "performance_result": fixture["expected_status"] == 0,
                "byte_comparison": fixture.get(
                    "output_comparison", "raw INT32 accumulator"
                ),
                "invocation": event_metrics(
                    invocation, "isolated_replay_invocation", fixture["work"]
                ),
                "unit": event_metrics(
                    unit, "inclusive_isolated_kernel", fixture["work"]
                ),
                "harness_overhead": metric(
                    sum(residual.values()),
                    "retired_instructions",
                    "measured",
                    "isolated_invocation_outside_unit",
                ),
            }
        )
    return result


def verify_replay(path):
    path, manifest = verify_archive(path, FORMAT)
    workload = json.loads((path / "workload.json").read_text())
    if manifest.get("host_build_evidence_sha256"):
        host = verify_snapshot(
            path / "host_build_evidence/manifest.json",
            manifest["host_build_evidence_sha256"],
        )
        target = json.loads((path / "build_evidence/manifest.json").read_text())
        if host["generation"]["artifacts"] != target["generation"]["artifacts"]:
            raise ValueError("replay host/target model identity differs")
    pack = path / "workspace/replay/fixtures.bin"
    if digest(pack) != workload["fixture_pack_sha256"]:
        raise ValueError("replay fixture pack changed")
    if (
        digest(path / "oracle-manifest.json") != workload["oracle_manifest_sha256"]
        or digest(path / "oracle-golden.json") != workload["oracle_golden_sha256"]
    ):
        raise ValueError("replay oracle identity differs")
    data = pack.read_bytes()
    for fixture in workload["fixtures"]:
        for blob in [*fixture["inputs"], fixture["output"]]:
            if (
                hashlib.sha256(
                    data[blob["offset"] : blob["offset"] + blob["bytes"]]
                ).hexdigest()
                != blob["sha256"]
            ):
                raise ValueError("replay fixture extent/hash mismatch")
    for kind in manifest["kinds"]:
        build = json.loads((path / kind / "build.json").read_text())
        if digest(local_file(path, build["binary"])) != build["binary_sha256"]:
            raise ValueError("replay binary identity differs")
        for name, sha in build["dependency_sha256"].items():
            if digest(local_file(path, build["dependency_files"][name])) != sha:
                raise ValueError("replay build dependency identity differs")
        for name in (
            ["ordinary-output.txt", "run1-output.txt", "run2-output.txt"]
            if kind == "rv64"
            else ["output.txt"]
        ):
            check_output((path / kind / name).read_text(), workload)
    rows = []
    if "rv64" in manifest["kinds"]:
        root, entries, ins, config = boundaries(path / "rv64/replay.elf", workload)
        if (path / "rv64/regions.txt").read_text() != config:
            raise ValueError("replay boundaries changed")
        for suffix in ("events.csv", "pcs.csv"):
            if (path / f"rv64/run1.{suffix}").read_bytes() != (
                path / f"rv64/run2.{suffix}"
            ).read_bytes():
                raise ValueError("repeated replay profiles differ")
        rows = load_profile(path / "rv64/run1", workload, root, entries, ins)
    return path, manifest, workload, rows


def report(path, output):
    path, manifest, workload, rows = verify_replay(path)
    output = Path(output).resolve()
    if output.is_relative_to(path):
        raise ValueError("report cannot modify sealed replay evidence")
    result = {
        "schema_version": 2,
        "artifact_id": path.name,
        "configuration": workload["configuration"],
        "scope": "isolated replay; not full inference",
        "build_evidence_sha256": manifest["build_evidence_sha256"],
        "cases": workload["cases"],
        "nodes": workload["nodes"],
        "kinds": manifest["kinds"],
        "binaries": {
            kind: json.loads((path / kind / "build.json").read_text())["binary_sha256"]
            for kind in manifest["kinds"]
        },
        "fixture_pack_sha256": workload["fixture_pack_sha256"],
        "oracle_manifest_sha256": workload["oracle_manifest_sha256"],
        "oracle_golden_sha256": workload["oracle_golden_sha256"],
        "fixtures_verified_per_build": len(workload["fixtures"]),
        "rows": rows,
        "limitations": [
            "Setup, restoration, poisoning and complete byte comparisons are outside the region.",
            "Scalar dot measurements include cc_dot's existing int64 overflow checks.",
            "Error outcomes are diagnostics, not successful performance results.",
            "Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.",
            "Spike retirements are not hardware cycles.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(canonical(result))
    lines = [
        f"# {workload['configuration']} isolated kernel investigation",
        "",
        f"Artifact: `{path.name}`.",
        f"Verified {len(workload['fixtures'])} fixtures per build ({', '.join(manifest['kinds'])}).",
        "",
        "| Fixture | Unit instructions | Harness overhead | Outcome |",
        "|---|---:|---:|---|",
    ]
    lines += [
        f"| {r['fixture']} | {r['unit']['instructions']['value']} | {r['harness_overhead']['value']} | {'performance' if r['performance_result'] else 'diagnostic error'} |"
        for r in rows
    ]
    lines += ["", *["- " + text for text in result["limitations"]], ""]
    (output / "README.md").write_text("\n".join(lines))
    print(
        f"Replay verified: {len(workload['fixtures'])} fixtures, {len(rows)} profiled invocations",
        flush=True,
    )
    return result


def replay(args):
    args.output_root = args.output_root.resolve()
    snapshot, evidence = open_build(args.build_manifest.resolve())
    if evidence["build"]["kind"] != "rv64" or evidence["build"][
        "configuration"
    ] not in ("A0", "B1", "X1", "X2", "X3"):
        raise ValueError("replay requires a verified production RV64 A0/B1 build")
    workload, pack = make_fixtures(
        snapshot, evidence, args.oracle, args.golden, args.nodes, args.cases
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".replay-", dir=args.output_root
    ) as temporary:
        work = Path(temporary) / "artifact"
        work.mkdir()
        prepare_sources(work, snapshot, evidence, workload, pack)
        host_identity = None
        if any(k != "rv64" for k in args.kinds):
            host_snapshot, host = open_build(args.host_build_manifest.resolve())
            if host["generation"]["artifacts"] != evidence["generation"][
                "artifacts"
            ] or host["build"]["kind"] not in ("native", "capture", "sanitized"):
                raise ValueError(
                    "host replay headers do not belong to the same generated model"
                )
            shutil.copytree(host_snapshot.parent, work / "host_build_evidence")
            host_identity = digest(host_snapshot)
            for name, obj in host["files"].items():
                if Path(name).is_absolute():
                    continue
                target = local_file(work / "workspace", name)
                if target.exists() and digest(target) != obj["sha256"]:
                    raise ValueError(f"host/target source disagreement: {name}")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(
                        local_file(host_snapshot.parent, obj["blob"]), target
                    )
        shutil.copyfile(args.oracle / "manifest.json", work / "oracle-manifest.json")
        shutil.copyfile(args.golden, work / "oracle-golden.json")
        source_root = work / "investigation_sources"
        source_root.mkdir()
        for source in [
            ROOT / "compiler/replay.py",
            ROOT / "tools/compiler/replay_driver.cc",
            *sorted((ROOT / "tools/investigation").glob("*.py")),
        ]:
            shutil.copyfile(source, source_root / source.name)
        collectors = {
            "ordinary_sha256": digest(ROOT / ".deps/spike/bin/spike"),
            "profile_sha256": digest(ROOT / ".deps/spike-profile/bin/spike"),
            "patch_sha256": digest(ROOT / "tools/spike_profile/spike.patch"),
            "header_sha256": digest(ROOT / "tools/spike_profile/roi_profiler.h"),
        }
        if workload["configuration"] in ("X1", "X2", "X3"):
            collectors["xqmac8"] = {
                v: extension_identity(v, workload["configuration"])
                for v in ("ordinary", "profile")
            }
        for name in ("spike.patch", "roi_profiler.h"):
            shutil.copyfile(ROOT / "tools/spike_profile" / name, source_root / name)
        for kind in args.kinds:
            binary = build_replay(work, evidence, kind)
            if kind == "rv64":
                root, entries, ins, config = boundaries(binary, workload)
                (work / "rv64/regions.txt").write_text(config)
                for repeat in (0, 1, 2):
                    collector = ROOT / (
                        ".deps/spike/bin/spike"
                        if not repeat
                        else ".deps/spike-profile/bin/spike"
                    )
                    command = spike_command(
                        workload["configuration"],
                        "ordinary" if not repeat else "profile",
                    )
                    if repeat:
                        command += [
                            f"--profile-config={work / 'rv64/regions.txt'}",
                            f"--profile-output={work / f'rv64/run{repeat}'}",
                        ]
                    command += [binary]
                    print(
                        f"Replay RV64: {'ordinary verification' if not repeat else f'profile {repeat}/2'}",
                        flush=True,
                    )
                    result = run(command, timeout=1800)
                    stem = "ordinary" if not repeat else f"run{repeat}"
                    (work / f"rv64/{stem}-output.txt").write_text(
                        result.stdout.replace("\r", "")
                    )
                    (work / f"rv64/{stem}-stderr.txt").write_text(result.stderr)
                    check_output(result.stdout, workload)
                    if repeat:
                        load_profile(
                            work / f"rv64/run{repeat}", workload, root, entries, ins
                        )
                for suffix in ("events.csv", "pcs.csv"):
                    if (work / f"rv64/run1.{suffix}").read_bytes() != (
                        work / f"rv64/run2.{suffix}"
                    ).read_bytes():
                        raise ValueError("replay repeat mismatch")
            else:
                result = run([binary], timeout=180)
                check_output(result.stdout, workload)
                (work / kind / "output.txt").write_text(result.stdout)
                (work / kind / "stderr.txt").write_text(result.stderr)
        if collectors["ordinary_sha256"] != digest(
            ROOT / ".deps/spike/bin/spike"
        ) or collectors["profile_sha256"] != digest(
            ROOT / ".deps/spike-profile/bin/spike"
        ):
            raise ValueError("simulator changed during replay collection")
        metadata = {
            "build_evidence_sha256": digest(snapshot),
            "kinds": args.kinds,
            "host_build_evidence_sha256": host_identity,
            "collector": collectors,
        }
        destination = seal(work, args.output_root, FORMAT, metadata)
    report(destination, args.results_dir)
    print(f"Replay artifact: {destination}", flush=True)
