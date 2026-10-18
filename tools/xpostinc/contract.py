"""Exact Xpostinc v1 encoding and independently derived memory results."""

LOADS = ("xlbpi", "xlhpi", "xlwpi", "xldpi", "xlbupi", "xlhupi", "xlwupi")
STORES = ("xsbpi", "xshpi", "xswpi", "xsdpi")
NAMES = LOADS + STORES
MASK = 0x707F
MASK64 = (1 << 64) - 1


def decode(bits, length=4):
    if length != 4:
        return None
    op, width = bits & 127, (bits >> 12) & 7
    names = LOADS if op == 0x2B else STORES if op == 0x7B else ()
    return names[width] if width < len(names) else None


def encode(name, value, base, increment):
    if name not in NAMES or not all(
        type(r) is int and 0 <= r < 32 for r in (value, base)
    ):
        raise ValueError("invalid Xpostinc mnemonic/register")
    if type(increment) is not int or not -2048 <= increment <= 2047:
        raise ValueError("increment must fit signed 12 bits")
    names, op = (LOADS, 0x2B) if name in LOADS else (STORES, 0x7B)
    return (
        op
        | (value << 7)
        | (names.index(name) << 12)
        | (base << 15)
        | ((increment & 4095) << 20)
    )


def load_oracle(name, memory):
    width = 1 << (LOADS.index(name) & 3)
    if len(memory) != width:
        raise ValueError("wrong memory width")
    return int.from_bytes(memory, "little", signed=LOADS.index(name) < 3) & MASK64
