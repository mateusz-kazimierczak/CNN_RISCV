"""ISA-aware adapters around the byte-frozen B0 disassembly and classification.

The B0 tools remain intact so the frozen baseline contract stays verifiable.
Only exact Xqmac8 encodings acquire the custom mnemonic.
"""

from tools.profile_spike import (
    classify as base_classify,
    disassemble as base_disassemble,
)
from tools.xqmac8.runtime import decode
from tools.xrequant.contract import decode as decode_requant


def classify(mnemonic):
    return "custom" if mnemonic in ("xqmac8", "xrequant") else base_classify(mnemonic)


def disassemble(elf):
    instructions = base_disassemble(elf)
    for instruction in instructions.values():
        bits = instruction["bits"]
        if decode(bits, instruction["length"]) or decode_requant(
            bits, instruction["length"]
        ):
            instruction["mnemonic"] = (
                "xqmac8" if decode(bits, instruction["length"]) else "xrequant"
            )
            instruction["operands"] = (
                f"x{(bits >> 7) & 31},x{(bits >> 15) & 31},x{(bits >> 20) & 31}"
            )
    return instructions
