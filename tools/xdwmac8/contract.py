"""Xdwmac8 v1 exact decoding and independent arbitrary-precision oracle."""

MASK64 = (1 << 64) - 1
NAMES = (
    "xdwmac8",
    *(f"xdwset{i}" for i in range(4)),
    *(f"xdwget{i}" for i in range(4)),
)


def decode(bits, length=4):
    if length != 4:
        return None
    if bits & 0xFE007FFF == 0x200B:
        return "xdwmac8"
    for i in range(4):
        if bits & 0xFFF07FFF == 0x300B | (i << 25):
            return f"xdwset{i}"
        if bits & 0xFFFFF07F == 0x400B | (i << 25):
            return f"xdwget{i}"
    return None


def encode(name, rd=0, rs1=0, rs2=0):
    if name not in NAMES or not all(
        type(r) is int and 0 <= r < 32 for r in (rd, rs1, rs2)
    ):
        raise ValueError("invalid bank instruction")
    word = (
        0x200B
        if name == "xdwmac8"
        else (0x300B if name.startswith("xdwset") else 0x400B) | (int(name[-1]) << 25)
    )
    word |= (rd << 7) | (rs1 << 15) | (rs2 << 20)
    if decode(word) != name:
        raise ValueError("reserved bank operand fields")
    return word


def oracle(lanes, a, w):
    s8 = lambda v: v if v < 128 else v - 256
    return [
        (v + s8((a >> (i * 8)) & 255) * s8((w >> (i * 8)) & 255)) & 0xFFFFFFFF
        for i, v in enumerate(lanes)
    ]
