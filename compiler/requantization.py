"""Explicit software scaling policies, selected only from prepared proofs.

The generic policy remains the default. These policies change neither the
reduction nor the prepared constants; X2 instruction selection is separate.
"""

from dataclasses import replace

from .ir import ModelError

REQUANTIZATIONS = ("generic", "nonpositive", "inline-nonpositive")
BACKENDS = {
    "nonpositive": "project_double_rounding_nonpositive",
    "inline-nonpositive": "project_double_rounding_nonpositive_inline",
}
POLICIES = {
    BACKENDS["nonpositive"]: "arch_project::numeric::NonpositiveRequantization",
    BACKENDS[
        "inline-nonpositive"
    ]: "arch_project::numeric::InlineNonpositiveRequantization",
}


def saved_requantization(nodes):
    # A hint for canonical reconstruction, never a substitute for validation.
    return next(
        (
            mode
            for mode in REQUANTIZATIONS[1:]
            if any(f"requantization_{mode}" in n["choices"] for n in nodes)
        ),
        "generic",
    )


def requantization_mode(plan):
    return saved_requantization([{"choices": n.choices} for n in plan.nodes])


def saved_requantization_overrides(nodes):
    return {
        n["node"]: mode
        for n in nodes
        for mode in REQUANTIZATIONS[1:]
        if f"requantization_override_{mode}" in n["choices"]
    }


def requantization_overrides(plan):
    return saved_requantization_overrides(
        [{"node": n.node, "choices": n.choices} for n in plan.nodes]
    )


def policy_arguments(selection):
    policy = (
        "arch_project::XRequantization"
        if selection.requantization_backend == "xrequant_v1"
        else POLICIES.get(selection.requantization_backend)
    )
    return () if policy is None else (("Requantization", policy),)


def apply_requantization(nodes, prepared, mode, overrides=None):
    overrides = {} if overrides is None else overrides
    if mode == "generic" and not overrides:
        return tuple(nodes)
    result = []
    selected = 0
    overridden = set()
    for node, parameters in zip(nodes, prepared.nodes):
        requested = overrides.get(node.node, mode)
        supports_policy = (
            node.implementation.startswith(
                ("rv64imc/pointwise_", "rv64imc/depthwise_", "project/stem_rgb3x3/")
            )
            and node.requantization_backend == "project_double_rounding"
        )
        backend = node.requantization_backend
        if supports_policy and node.nonpositive_shifts and requested != "generic":
            shifts = parameters.integers["shifts"]
            multipliers = parameters.integers["multipliers"]
            if not (
                len(shifts) == len(multipliers) == node.geometry.output_shape[-1]
                and all(-31 <= shift <= 0 for shift in shifts)
                and all(0 <= multiplier <= 2**31 - 1 for multiplier in multipliers)
            ):
                raise ModelError(f"node {node.node}: invalid nonpositive scaling proof")
            backend = BACKENDS[requested]
            selected += 1
            if node.node in overrides:
                overridden.add(node.node)
        result.append(
            replace(
                node,
                requantization_backend=backend,
                choices=(
                    *node.choices,
                    f"requantization_{mode}",
                    *(
                        (f"requantization_override_{requested}",)
                        if node.node in overridden
                        else ()
                    ),
                ),
            )
        )
    if not selected:
        raise ModelError("requantization policy requires a proven project convolution")
    if set(overrides) != overridden:
        raise ModelError(
            "requantization override requires a proven project convolution"
        )
    return tuple(result)
