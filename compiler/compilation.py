"""One compilation's verified preparation; no process-global or mutable-object cache."""

import hashlib
from dataclasses import dataclass

from .ir import Graph, ModelError
from .quantization import PreparedGraph, prepare_graph


@dataclass(frozen=True, init=False)
class CompilationContext:
    _graph_json: str
    graph_sha256: str
    prepared: PreparedGraph
    _prepared_json: str

    def __init__(self, graph: Graph):
        graph_json = graph.to_json()
        prepared = prepare_graph(graph)
        object.__setattr__(self, "_graph_json", graph_json)
        object.__setattr__(
            self, "graph_sha256", hashlib.sha256(graph_json.encode()).hexdigest()
        )
        object.__setattr__(self, "prepared", prepared)
        # Keep bytes independent of the PreparedNode.integers dictionaries.
        object.__setattr__(self, "_prepared_json", prepared.to_json())

    def check(self, graph: Graph, prepared: PreparedGraph) -> None:
        if graph.to_json() != self._graph_json:
            raise ModelError("compilation graph changed; start a new compilation")
        if prepared.to_json() != self._prepared_json:
            raise ModelError("prepared parameters differ from validated graph")
