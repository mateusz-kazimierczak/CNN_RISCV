"""Xrequant v1 descriptor and independent integer semantics (W8A8)."""

MATCH, MASK = 0x0000100B, 0xFE00707F
SCALE_ONLY = 1 << 62
MASK64 = (1 << 64) - 1


def decode(bits, length):
    return length == 4 and bits & MASK == MATCH


def pack(multiplier, shift, zero=0, minimum=0, maximum=0, *, scale_only=False):
    if not (
        type(multiplier) is int
        and 0 <= multiplier < 2**31
        and type(shift) is int
        and -31 <= shift <= 0
        and all(type(x) is int and -128 <= x <= 127 for x in (zero, minimum, maximum))
        and minimum <= maximum
        and type(scale_only) is bool
    ):
        raise ValueError("invalid Xrequant descriptor")
    if scale_only and (zero or minimum or maximum):
        raise ValueError("scale-only descriptors require zero output fields")
    return (
        multiplier
        | (-shift << 32)
        | ((zero & 255) << 38)
        | ((minimum & 255) << 46)
        | ((maximum & 255) << 54)
        | (SCALE_ONLY if scale_only else 0)
    )


def unpack(descriptor):
    def signed8(x):
        return x if x < 128 else x - 256

    m, r = descriptor & 0xFFFFFFFF, (descriptor >> 32) & 63
    z, lo, hi = (signed8((descriptor >> bit) & 255) for bit in (38, 46, 54))
    scale = bool(descriptor & SCALE_ONLY)
    if (
        not 0 <= descriptor <= MASK64
        or descriptor >> 63
        or m >= 2**31
        or r > 31
        or lo > hi
        or (scale and (z or lo or hi))
    ):
        raise ValueError("reserved Xrequant descriptor")
    return m, r, z, lo, hi, scale


def oracle(accumulator, descriptor):
    m, r, z, lo, hi, scale = unpack(descriptor)
    x = accumulator & 0xFFFFFFFF
    if x >= 2**31:
        x -= 2**32
    # Match gemmlowp's signed nudge and truncation, independently of the C++
    # implementation's floor-shift identity.
    product = x * m
    numerator = product + (2**30 if product >= 0 else 1 - 2**30)
    high = (1 if numerator >= 0 else -1) * (abs(numerator) // 2**31)
    magnitude = (abs(high) + (2 ** (r - 1) if r else 0)) // 2**r
    value = magnitude if high >= 0 else -magnitude
    if not scale:
        value = max(lo, min(hi, value + z))
    return value & MASK64
