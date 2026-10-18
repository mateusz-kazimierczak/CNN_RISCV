"""Canonical X2 selection and offline packed descriptors; prepared IR is immutable."""

from dataclasses import replace
from .ir import ModelError
from tools.xrequant.contract import pack, oracle

BACKEND = "xrequant_v1"
OUTLINE_CHOICE = "xrequant_depthwise_pixel_outlined"
ADD64_CHOICE = "xrequant_add_register_64_int32_bounds_proven"


def optimization_options(nodes):
    choices = {
        c for n in nodes for c in (n["choices"] if isinstance(n, dict) else n.choices)
    }
    return {
        "xrequant_depthwise_outlining": "selected"
        if OUTLINE_CHOICE in choices
        else "none",
        "xrequant_add_register_bits": 64 if ADD64_CHOICE in choices else 32,
    }


def outline_eligible(selection):
    """Measured geometry families for this model and the pinned RV64 GCC."""
    g = selection.geometry
    return selection.implementation.startswith("rv64imc/depthwise_") and (
        (g.weight_shape[1:3] == (3, 3) and g.stride == (1, 1))
        or g.input_shape[-1] == 672
    )


def add_int32_bounds(values):
    """Prove wide register storage preserves the existing INT32 ADD domain.

    Nonnegative multipliers and both rounding operations are monotone. Scaling
    the two endpoints therefore bounds all 256 possible INT8 input values.
    """

    def checked(lo, hi):
        if not -(2**31) <= lo <= hi < 2**31:
            raise ModelError(
                "Xrequant wide ADD requires proven INT32 input and sum bounds"
            )
        return lo, hi

    shift = values["left_shift"]
    if type(shift) is not int or not 0 <= shift <= 30:
        raise ModelError("Xrequant wide ADD requires a checked left shift")
    scaled = []
    for prefix in ("input1", "input2"):
        lo, hi = checked(
            (-128 + values[prefix + "_offset"]) * (1 << shift),
            (127 + values[prefix + "_offset"]) * (1 << shift),
        )
        descriptor = pack(
            values[prefix + "_multiplier"], values[prefix + "_shift"], scale_only=True
        )
        endpoints = [oracle(x, descriptor) for x in (lo, hi)]
        scaled.append(checked(*(x if x < 2**63 else x - 2**64 for x in endpoints)))
    return checked(sum(x[0] for x in scaled), sum(x[1] for x in scaled))


def packed_words(node):
    p = node.integers
    values = []
    for m, s in zip(p["multipliers"], p["shifts"], strict=True):
        d = pack(
            m,
            s,
            p["output_zero_point"],
            p["output_activation_min"],
            p["output_activation_max"],
        )
        for word in (d & 0xFFFFFFFF, d >> 32):
            values.append(word if word < 2**31 else word - 2**32)
    return values


def select_x2(
    parent, graph, prepared, *, depthwise_outlining="none", add_register_bits=32
):
    if not any(n.reduction_backend.startswith("xqmac8") for n in parent.nodes):
        raise ModelError("X2 requires the X1 MAC backend")
    selections = []
    for n, p in zip(parent.nodes, prepared.nodes):
        if n.kind not in ("CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED", "ADD"):
            selections.append(n)
            continue
        if n.kind in ("CONV_2D", "DEPTHWISE_CONV_2D"):
            if not (
                n.nonpositive_shifts
                and (
                    n.implementation.startswith(
                        (
                            "rv64imc/pointwise_",
                            "rv64imc/depthwise_",
                            "project/stem_rgb3x3/",
                        )
                    )
                )
            ):
                raise ModelError(
                    f"node {n.node}: X2 requires a supported nonpositive output policy"
                )
            packed_words(p)  # validate every descriptor before memory planning
            memory = replace(n.memory, parameter_format=BACKEND)
        else:
            values = p.integers
            if n.kind == "FULLY_CONNECTED":
                pack(
                    values["output_multiplier"],
                    values["output_shift"],
                    values["output_zero_point"],
                    values["output_activation_min"],
                    values["output_activation_max"],
                )
            else:
                for prefix in ("input1", "input2"):
                    pack(
                        values[prefix + "_multiplier"],
                        values[prefix + "_shift"],
                        scale_only=True,
                    )
                pack(
                    values["output_multiplier"],
                    values["output_shift"],
                    values["output_offset"],
                    values["output_activation_min"],
                    values["output_activation_max"],
                )
            memory = n.memory
        choices = (*n.choices, BACKEND)
        if depthwise_outlining == "selected" and outline_eligible(n):
            choices += (OUTLINE_CHOICE,)
        if add_register_bits == 64 and n.kind == "ADD":
            add_int32_bounds(p.integers)
            choices += (ADD64_CHOICE,)
        selections.append(
            replace(
                n,
                requantization_backend=BACKEND,
                choices=choices,
                memory=memory,
            )
        )
    result = replace(parent, configuration="X2", nodes=tuple(selections))
    if optimization_options(result.nodes) != {
        "xrequant_depthwise_outlining": depthwise_outlining,
        "xrequant_add_register_bits": add_register_bits,
    }:
        raise ModelError("requested Xrequant optimization has no eligible kernels")
    return result
