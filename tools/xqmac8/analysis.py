"""ISA-aware adapters around the byte-frozen B0 disassembly and classification.

The B0 tools remain intact so the frozen baseline contract stays verifiable.
Only exact Xqmac8 encodings acquire the custom mnemonic.
"""
from tools.profile_spike import classify as base_classify, disassemble as base_disassemble
from tools.xqmac8.runtime import decode


def classify(mnemonic):
    return "custom" if mnemonic == "xqmac8" else base_classify(mnemonic)


def disassemble(elf):
    instructions = base_disassemble(elf)
    for instruction in instructions.values():
        bits = instruction["bits"]
        if decode(bits, instruction["length"]):
            instruction["mnemonic"] = "xqmac8"
            instruction["operands"] = f"x{(bits >> 7) & 31},x{(bits >> 15) & 31},x{(bits >> 20) & 31}"
    return instructions
