"""Reproducible UINT8 inputs; the seed-1 LCG matches tflm/efficientnet_lite0.cc."""

from __future__ import annotations

from dataclasses import dataclass

INPUT_BYTES = 224 * 224 * 3
INPUT_ZERO_POINT = 131


def lcg_bytes(size: int, seed: int = 1) -> bytes:
    if size < 0 or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("size must be nonnegative and seed must fit uint32")
    result = bytearray(size)
    state = seed
    for index in range(size):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        result[index] = state >> 24
    return bytes(result)


def fnv1a(data: bytes) -> str:
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return f"0x{value:08x}"


@dataclass(frozen=True)
class InputCase:
    name: str
    pattern: str
    seed: int | None = None
    expected_nodes: int = 64
    expected_signal: str | None = None

    def data(self) -> bytes:
        if self.pattern == "lcg":
            if self.seed is None:
                raise ValueError("LCG input requires a seed")
            return lcg_bytes(INPUT_BYTES, self.seed)
        if self.pattern == "zeros":
            return bytes(INPUT_BYTES)
        if self.pattern == "maximum":
            return bytes([255]) * INPUT_BYTES
        if self.pattern == "zero_point":
            return bytes([INPUT_ZERO_POINT]) * INPUT_BYTES
        if self.pattern == "alternating":
            return bytes([0, 255]) * (INPUT_BYTES // 2)
        if self.pattern == "ramp":
            return bytes(index & 255 for index in range(INPUT_BYTES))
        raise ValueError(f"unknown input pattern: {self.pattern}")


CASES = (
    InputCase("baseline", "lcg", 1),
    InputCase("zeros", "zeros"),
    InputCase("maximum", "maximum"),
    # The pinned reference aborts at node 62's Softmax exponent check.
    # Record the counterexample; do not turn incomplete output into a golden result.
    InputCase("zero_point", "zero_point", expected_nodes=62, expected_signal="SIGABRT"),
    InputCase("alternating", "alternating"),
    InputCase("ramp", "ramp"),
    InputCase("random_42", "lcg", 42),
    InputCase("random_deadbeef", "lcg", 0xDEADBEEF),
)
