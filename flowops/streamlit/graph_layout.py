"""Deterministic, position-only layout for drafts; no browser or engine side effects."""

from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Runbook
from flowops.persistence.repository import digest


def _layout_signature(book: Runbook, revision: int) -> str:
    # Configuration edits are deliberately excluded: undo must preserve them.
    return digest(
        {
            "id": book.id,
            "revision": revision,
            "nodes": [(node.id, node.position) for node in book.nodes],
            "edges": [edge.model_dump() for edge in book.edges],
        }
    )


@dataclass(frozen=True)
class LayoutUndo:
    positions: dict[str, tuple[float, float]]
    organized_signature: str

    def matches(self, book: Runbook, revision: int) -> bool:
        return self.organized_signature == _layout_signature(book, revision)

    def restore(self, book: Runbook, revision: int) -> Runbook:
        if not self.matches(book, revision):
            raise WorkflowValidationError(
                "Não é possível desfazer: as posições, conexões ou a revisão foram alteradas."
            )
        restored = book.model_copy(deep=True)
        for node in restored.nodes:
            node.position = self.positions[node.id]
        return restored


def organize_workflow(book: Runbook, revision: int) -> tuple[Runbook, LayoutUndo | None]:
    """Layer a DAG left-to-right without reordering definitions or inventing edges.

    Incomplete and disconnected drafts are allowed; this is not execution validation.
    Fixed spacing matches the canvas's 190px cards, not a general edge-routing solver.
    """
    if len(book.nodes) > 200 or len(book.edges) > 1000:
        raise WorkflowValidationError("O fluxo excedeu o limite de tamanho.")
    incoming: dict[str, set[str]] = {node.id: set() for node in book.nodes}
    if len(incoming) != len(book.nodes):
        raise WorkflowValidationError("Não é possível organizar etapas com IDs repetidos.")
    for edge in book.edges:
        if edge.source not in incoming or edge.target not in incoming:
            raise WorkflowValidationError("Uma conexão do fluxo aponta para uma etapa removida.")
        incoming[edge.target].add(edge.source)
    try:
        ordered = list(TopologicalSorter(incoming).static_order())
    except CycleError as exc:
        raise WorkflowValidationError(
            "Não é possível organizar um fluxo com ciclos. Revise as conexões."
        ) from exc

    depth: dict[str, int] = {}
    for node_id in ordered:
        depth[node_id] = max((depth[parent] + 1 for parent in incoming[node_id]), default=0)
    layers: dict[int, list[str]] = {}
    for node in book.nodes:
        layers.setdefault(depth[node.id], []).append(node.id)
    width = max((len(layer) for layer in layers.values()), default=0)
    positions: dict[str, tuple[float, float]] = {}
    for level, layer in sorted(layers.items()):
        # Stable ties retain declaration order; parent centers reduce obvious crossings.
        layer.sort(
            key=lambda node_id: (
                sum(positions[parent][1] for parent in incoming[node_id])
                / max(1, len(incoming[node_id]))
            )
        )
        for row, node_id in enumerate(layer):
            positions[node_id] = (40.0 + level * 320, 40.0 + (width - len(layer)) * 180 + row * 360)

    result = book.model_copy(deep=True)
    before = {node.id: node.position for node in book.nodes}
    for node in result.nodes:
        node.position = positions[node.id]
    undo = LayoutUndo(before, _layout_signature(result, revision)) if before != positions else None
    return result, undo
