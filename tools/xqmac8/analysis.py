"""ISA-aware adapters around the byte-frozen B0 disassembly and classification.

The B0 tools remain intact so the frozen baseline contract stays verifiable.
Only exact Xqmac8 encodings acquire the custom mnemonic.
"""

from tools.profile_spike import (
    classify as base_classify,
)
from tools.profile_spike import (
    disassemble as base_disassemble,
)
from tools.xpostinc.contract import LOADS, STORES
from tools.xdwmac8.contract import NAMES as DW_NAMES, decode as decode_dw
from tools.xpostinc.contract import decode as decode_postinc
from tools.xqmac8.runtime import decode
from tools.xrequant.contract import decode as decode_requant


def classify(mnemonic):
    if mnemonic in LOADS:
        return "load"
    if mnemonic in STORES:
        return "store"
    return (
        "custom"
        if mnemonic in ("xqmac8", "xrequant", *DW_NAMES)
        else base_classify(mnemonic)
    )


def disassemble(elf):
    instructions = base_disassemble(elf)
    for instruction in instructions.values():
        bits = instruction["bits"]
        dw = decode_dw(bits, instruction["length"])
        if dw:
            instruction["mnemonic"] = dw
            instruction["operands"] = (
                f"x{(bits >> 15) & 31},x{(bits >> 20) & 31}"
                if dw == "xdwmac8"
                else f"x{(bits >> 15) & 31}"
                if dw.startswith("xdwset")
                else f"x{(bits >> 7) & 31}"
            )
        postinc = decode_postinc(bits, instruction["length"])
        if postinc:
            increment = bits >> 20
            if increment & 2048:
                increment -= 4096
            instruction["mnemonic"] = postinc
            instruction["operands"] = (
                f"x{(bits >> 7) & 31},x{(bits >> 15) & 31},{increment}"
            )
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
