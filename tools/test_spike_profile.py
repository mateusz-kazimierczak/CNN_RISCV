#!/usr/bin/env python3
"""Host unit checks plus directed, hand-counted Spike collector integration."""

from __future__ import annotations
import collections
import csv
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import shutil

from profile_spike import (
    ROOT,
    Elf,
    classify,
    disassemble,
    symbols,
    unique_symbol,
    valid_axis_products,
    validate_elf,
    load_capture,
)

SOURCE = ROOT / "tools/spike_profile/tests"
PREFIX = ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-"
SPIKE = ROOT / ".deps/spike-profile/bin/spike"
STOCK = ROOT / ".deps/spike/bin/spike"


def rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


class AnalysisTests(unittest.TestCase):
    def test_capture_validation(self):
        with tempfile.TemporaryDirectory(prefix="spike-analysis-test-") as directory:
            prefix = Path(directory) / "capture"
            events = [
                dict(
                    event_id=0,
                    kind="region",
                    name="allocate",
                    entry=128,
                    return_pc=0,
                    complete=1,
                    status=0,
                    total=2,
                    faulted=0,
                ),
                dict(
                    event_id=1,
                    kind="region",
                    name="invoke",
                    entry=256,
                    return_pc=0,
                    complete=1,
                    status=0,
                    total=5,
                    faulted=0,
                ),
                dict(
                    event_id=2,
                    kind="operator",
                    name="ADD",
                    entry=512,
                    return_pc=0,
                    complete=1,
                    status=0,
                    total=2,
                    faulted=0,
                ),
            ]
            hist = [
                dict(event_id=0, pc=128, bits=1, length=2, count=2),
                dict(event_id=1, pc=256, bits=1, length=2, count=3),
                dict(event_id=1, pc=512, bits=1, length=2, count=2),
                dict(event_id=2, pc=512, bits=1, length=2, count=2),
            ]
            instructions = {
                pc: dict(bits=1, length=2, mnemonic="c.nop") for pc in (128, 256, 512)
            }

            def write():
                for name, data in (("events", events), ("pcs", hist)):
                    with Path(str(prefix) + f".{name}.csv").open("w", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=list(data[0]))
                        writer.writeheader()
                        writer.writerows(data)

            write()
            self.assertEqual(
                load_capture(prefix, [{"type": "ADD"}], instructions)[3], 3
            )
            for field, value in (
                ("complete", 0),
                ("status", 1),
                ("faulted", 1),
                ("total", 3),
                ("name", "RESHAPE"),
            ):
                with self.subTest(field=field):
                    old = events[2][field]
                    events[2][field] = value
                    write()
                    with self.assertRaises(ValueError):
                        load_capture(prefix, [{"type": "ADD"}], instructions)
                    events[2][field] = old
            hist[3]["bits"] = 2
            write()
            with self.assertRaises(ValueError):
                load_capture(prefix, [{"type": "ADD"}], instructions)
            hist[3]["bits"] = 1
            hist.append(hist[-1].copy())
            write()
            with self.assertRaises(ValueError):
                load_capture(prefix, [{"type": "ADD"}], instructions)

    def test_instruction_categories(self):
        for mnemonic, expected in (
            ("c.ldsp", "load"),
            ("c.sw", "store"),
            ("mulw", "multiply"),
            ("divw", "divide_remainder"),
            ("c.jr", "jump"),
            ("c.beqz", "conditional_branch"),
            ("c.addiw", "integer_alu"),
            ("csrrs", "other"),
        ):
            self.assertEqual(classify(mnemonic), expected)
        for unknown in ("unknown", ".word", "fadd.s", "vadd.vv", "amoadd.d", "xqmac8"):
            with self.assertRaises(ValueError):
                classify(unknown)

    def test_padding_products(self):
        self.assertEqual(valid_axis_products(3, 3, 3, 1, 1, True), 7)
        self.assertEqual(valid_axis_products(3, 1, 3, 1, 1, False), 3)
        self.assertEqual(valid_axis_products(4, 2, 3, 2, 1, True), 5)
        self.assertEqual(valid_axis_products(3, 3, 3, 1, 2, True), 5)


class CollectorTests(unittest.TestCase):
    def test_native_collector(self):
        with tempfile.TemporaryDirectory(prefix="spike-profile-test-") as directory:
            temp = Path(directory)
            config = temp / "regions.txt"
            config.write_text(
                "code 0x100 0x300\nregion invoke 0x100\noperator ADD 0x200\n"
            )
            binary = temp / "collector-test"
            env = dict(os.environ)
            if shutil.which("xcrun"):
                env["SDKROOT"] = subprocess.check_output(
                    ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
                ).strip()
            subprocess.run(
                [
                    "c++",
                    "-std=c++17",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT / "tools/spike_profile"),
                    str(SOURCE / "collector_test.cc"),
                    "-o",
                    str(binary),
                ],
                check=True,
                env=env,
            )
            output = temp / "capture"
            subprocess.run([str(binary), str(config), str(output)], check=True)
            partial = rows(Path(str(output) + ".events.csv"))
            self.assertEqual(partial[0]["complete"], "0")
            self.assertEqual(partial[0]["faulted"], "1")

    def test_spike_retirement(self):
        with tempfile.TemporaryDirectory(
            prefix="spike-profile-integration-"
        ) as directory:
            temp = Path(directory)
            for case, extra, delta, fault in (
                ("normal", [], 0, 0),
                ("serialization", ["-DSERIALIZE"], 1, 0),
                ("trap", ["-DTRAP"], 4, 1),
            ):
                with self.subTest(case=case):
                    elf = temp / f"{case}.elf"
                    isa = "rv64imc" if not extra else "rv64imc_zicsr"
                    command = [
                        str(PREFIX) + "gcc",
                        "-march=" + isa,
                        "-mabi=lp64",
                        "-nostdlib",
                        "-g",
                        "-Wl,--no-relax",
                        "-Wl,-T," + str(ROOT / "tflm/platform/rv64imc/link.ld"),
                        *extra,
                        str(SOURCE / "fixture.S"),
                        "-o",
                        str(elf),
                    ]
                    subprocess.run(command, check=True)
                    section, names = Elf(elf).sections[".text"], symbols(elf)
                    config = temp / f"{case}.txt"
                    config.write_text(
                        f"code {section['address']:#x} {section['address'] + section['size']:#x}\nregion allocate {unique_symbol(names, 'allocate'):#x}\nregion invoke {unique_symbol(names, 'invoke'):#x}\noperator ADD {unique_symbol(names, 'toy_operator'):#x}\n"
                    )
                    output = temp / case
                    subprocess.run(
                        [
                            str(SPIKE),
                            "--isa=" + isa,
                            "--profile-config=" + str(config),
                            "--profile-output=" + str(output),
                            str(elf),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    events = rows(Path(str(output) + ".events.csv"))
                    self.assertEqual(
                        [int(e["total"]) for e in events], [2, 27 + delta, 20 + delta]
                    )
                    self.assertTrue(
                        all(
                            int(e["complete"]) == 1
                            and int(e["status"]) == 0
                            and int(e["faulted"]) == fault
                            for e in events
                        )
                    )
                    instructions = disassemble(elf)
                    hist = rows(Path(str(output) + ".pcs.csv"))
                    mix = collections.Counter()
                    for row in hist:
                        if row["event_id"] == "1":
                            pc = int(row["pc"])
                            self.assertEqual(int(row["bits"]), instructions[pc]["bits"])
                            mix[classify(instructions[pc]["mnemonic"])] += int(
                                row["count"]
                            )
                            self.assertNotEqual(instructions[pc]["mnemonic"], "ecall")
                    self.assertEqual(mix["multiply"], 3)
                    self.assertEqual(mix["divide_remainder"], 3)
                    self.assertEqual(mix["load"], 4)
                    self.assertEqual(mix["store"], 1)
                    self.assertEqual(mix["conditional_branch"], 3)
                    if not fault:
                        self.assertEqual(
                            load_capture(output, [{"type": "ADD"}], instructions)[3], 7
                        )
                    else:
                        with self.assertRaises(ValueError):
                            load_capture(output, [{"type": "ADD"}], instructions)
                    # Stock's commit log is an independent oracle on the ordinary
                    # non-serialized test, small enough to capture exhaustively.
                    if case == "normal":
                        log = subprocess.run(
                            [str(STOCK), "--isa=" + isa, "--log-commits", str(elf)],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        ).stderr
                        commits = collections.Counter(
                            int(pc, 16)
                            for pc in re.findall(
                                r"core\s+\d+:\s+\d\s+(0x[0-9a-f]+)\s+\(", log
                            )
                        )
                        self.assertTrue(commits)
                        for row in hist:
                            self.assertEqual(int(row["count"]), commits[int(row["pc"])])
                        sequence = [
                            int(pc, 16)
                            for pc in re.findall(
                                r"core\s+\d+:\s+\d\s+(0x[0-9a-f]+)\s+\(", log
                            )
                        ]
                        limit = sequence.index(unique_symbol(names, "invoke")) + 2
                        partial = temp / "partial"
                        subprocess.run(
                            [
                                str(SPIKE),
                                "--isa=" + isa,
                                "--instructions=" + str(limit),
                                "--profile-config=" + str(config),
                                "--profile-output=" + str(partial),
                                str(elf),
                            ],
                            check=True,
                            capture_output=True,
                            timeout=30,
                        )
                        self.assertTrue(
                            any(
                                e["complete"] == "0"
                                for e in rows(Path(str(partial) + ".events.csv"))
                            )
                        )
                        with self.assertRaises(ValueError):
                            load_capture(partial, [{"type": "ADD"}], instructions)
                    # Loaded sections differ even though both are valid ELFs.
                    if case == "normal":
                        normal_elf = elf
                    elif case == "serialization":
                        with self.assertRaises(ValueError):
                            validate_elf(normal_elf, elf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
