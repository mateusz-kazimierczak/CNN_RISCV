"""Directed checks for linked boundary extraction and complete-run acceptance."""

import copy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.cvw.collect_custom import validate_pass
from tools.cvw.export_custom_inputs import linked_addresses


class LinkedEvidenceTests(unittest.TestCase):
    def test_decodes_call_and_negative_output_offset(self):
        instructions = {
            0x1000: {"bits": 0x100000ef},  # jal ra, 0x1100
            0x2000: {"bits": 0x004bc517},
            0x2004: {"bits": 0xe8c50513},  # addi a0,a0,-372
        }
        symbols = [{"name": "main", "address": 0x1000, "size": 4}, {"name": "a0_output", "address": 0x2000, "size": 8}]
        returned, (output, _) = linked_addresses(instructions, symbols, 0x1100)
        self.assertEqual(returned, 0x1004)
        self.assertEqual(output, 0x2000 + 0x4bc000 - 372)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            linked_addresses(instructions, symbols, 0x1102)


class RunAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.output = bytes(i % 256 for i in range(1000))
        self.sha = hashlib.sha256(self.output).hexdigest()
        self.work = {"elf_sha256": "a" * 64, "expected_instructions": "100", "custom_instructions": {"xqmac8": "8", "xrequant": "3"}}
        self.record = {"elf_sha256": "a" * 64, "workload": self.work, "metrics": {"instructions": "100", "cycles": "123", "custom_instructions": {"xqmac8": "8", "xrequant": "3"}}, "output_bytes_compared": 1000, "output_sha256": self.sha, "cpi": {"numerator": "123", "denominator": "100"}}

    def test_accepts_complete_consistent_evidence(self):
        self.assertEqual(validate_pass(self.record, self.work, self.sha, self.output), self.record["metrics"])

    def test_rejects_mismatched_binary_counts_cycles_and_cpi(self):
        for field, value in (("elf_sha256", "b" * 64), ("instructions", "99"), ("custom_instructions", {"xqmac8": "7", "xrequant": "4"}), ("cycles", str(2**64)), ("cpi", {"numerator": "124", "denominator": "100"})):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                (record["metrics"] if field in record["metrics"] else record)[field] = value
                with self.assertRaises(ValueError):
                    validate_pass(record, self.work, self.sha, self.output)

    def test_rejects_truncated_and_corrupted_output(self):
        for output in (self.output[:-1], bytes(1000)):
            with self.assertRaises(ValueError):
                validate_pass(self.record, self.work, self.sha, output)

    def test_rejects_postincrement_counts_even_if_their_sum_matches(self):
        workload = copy.deepcopy(self.work)
        workload["custom_instructions"].update(xpostinc_load="12", xpostinc_store="4")
        record = copy.deepcopy(self.record)
        record["workload"] = workload
        record["metrics"]["custom_instructions"] = dict(workload["custom_instructions"])
        validate_pass(record, workload, self.sha, self.output)
        record["metrics"]["custom_instructions"].update(xpostinc_load="11", xpostinc_store="5")
        with self.assertRaises(ValueError):
            validate_pass(record, workload, self.sha, self.output)

    def test_reconciles_each_bank_transfer_form(self):
        workload = copy.deepcopy(self.work)
        workload["custom_instructions"].update(xdwmac8="9", **{f"xdw{form}{i}": "2" for form in ("set", "get") for i in range(4)})
        record = copy.deepcopy(self.record)
        record["workload"] = workload
        record["metrics"]["custom_instructions"] = dict(workload["custom_instructions"])
        validate_pass(record, workload, self.sha, self.output)
        record["metrics"]["custom_instructions"].update(xdwset1="1", xdwset2="3")
        with self.assertRaises(ValueError):
            validate_pass(record, workload, self.sha, self.output)


if __name__ == "__main__":
    unittest.main()
