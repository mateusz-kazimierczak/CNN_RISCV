"""Independent arbitrary-precision ISA oracle and deterministic RTL handoff vectors."""

import random

MASK64 = (1 << 64) - 1


def oracle(accumulator, a, w):
    def signed(byte):
        return byte if byte < 128 else byte - 256

    total = (accumulator & 0xFFFFFFFF) + sum(
        signed((a >> (8 * lane)) & 255) * signed((w >> (8 * lane)) & 255)
        for lane in range(8)
    )
    low = total % (1 << 32)
    return (low if low < (1 << 31) else low - (1 << 32)) & MASK64


def vectors():
    rng = random.Random(0x514D414338)
    cases = []

    def add(rd, rs1, rs2, registers, name):
        registers = {0: 0, **registers}
        registers[0] = 0
        result = oracle(registers[rd], registers[rs1], registers[rs2]) if rd else 0
        cases.append(
            dict(
                name=name,
                rd=rd,
                rs1=rs1,
                rs2=rs2,
                registers={str(k): f"{v:016x}" for k, v in registers.items()},
                expected_rd=f"{result:016x}",
            )
        )

    for acc in (0, 1, 0x7FFFFFFF, 0x80000000, MASK64, 0xDEADBEEF00000001):
        for a, w in (
            (0, 0),
            (0x8080808080808080, 0x8080808080808080),
            (0x7F7F7F7F7F7F7F7F, 0x8080808080808080),
            (0x010203040506077F, 0x807F01FF02030405),
        ):
            add(5, 6, 7, {5: acc, 6: a, 7: w}, "directed")
    for lane in range(8):
        for other in range(8):
            add(
                5,
                6,
                7,
                {5: 123, 6: 0x80 << (8 * lane), 7: 0x7F << (8 * other)},
                "lane-order",
            )
    for _ in range(10000):
        add(5, 6, 7, {r: rng.getrandbits(64) for r in (5, 6, 7)}, "random")
    for rd, rs1, rs2 in (
        (5, 5, 7),
        (5, 6, 5),
        (5, 6, 6),
        (5, 5, 5),
        (0, 6, 7),
        (5, 0, 7),
        (5, 6, 0),
    ):
        for _ in range(100):
            add(
                rd, rs1, rs2, {r: rng.getrandbits(64) for r in (5, 6, 7)}, "alias-or-x0"
            )
    acc = 0x7FFFFFF0
    for _ in range(64):
        a, w = rng.getrandbits(64), rng.getrandbits(64)
        add(5, 6, 7, {5: acc, 6: a, 7: w}, "accumulation-chain")
        acc = oracle(acc, a, w)
    return cases
