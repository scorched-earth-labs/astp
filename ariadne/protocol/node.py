"""
Ariadne Protocol v2 — Cognitive Node Primitives

CognitiveNode is the universal protocol primitive. All node types
(episodes, signals, agents, artifacts) are parameterizations of
CognitiveNode via the NodePayload interface.

The protocol layer operates on CognitiveNode exclusively. It never
inspects payload internals — only calls validate() and to_content_hash().
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class NodePayload(ABC):
    """Abstract interface for node-type-specific payload data.

    Protocol code calls only these methods — never inspects
    the payload's internal structure. This is the abstraction
    boundary that keeps the protocol layer node-generic.
    """

    @abstractmethod
    def validate(self) -> None:
        """Validate payload-specific invariants. Raises ValueError on failure."""
        ...

    @abstractmethod
    def to_content_hash_input(self) -> bytes:
        """Return canonical byte representation for content_hash computation.

        Must be deterministic: same payload state always produces same bytes.
        Implementations should use sorted-key JSON or a fixed binary format.
        """
        ...

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize payload to a dictionary for storage."""
        ...


class CognitiveNode(BaseModel):
    """The universal cognitive node — foundation of the Ariadne protocol.

    Every piece of agent cognition (episodes, segments, signals, artifacts)
    is represented as a CognitiveNode. The node_type field and payload
    carry type-specific semantics; the protocol layer treats all nodes
    identically for hashing, verification, and governance.
    """
    # Identity
    node_id: UUID = Field(default_factory=uuid4)
    node_type: str  # Open string, validated via NodeTypeRegistry
    schema_version: str = "2.0.0"

    # Dual index — the epistemological core of v2
    sequence_index: int  # IMMUTABLE: cognitive timeline position (in hash preimage)
    tree_leaf_index: int = 0  # MUTABLE: physical Merkle position (NOT in hash)

    # Content
    content_hash: str  # SHA3-256 of payload via to_content_hash_input()

    # Authorship
    authored_by: str  # Agent identity

    # Temporal
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sealed_at: Optional[datetime] = None

    # Graph position (immutable — reparenting is a governance violation)
    parent_node_id: Optional[UUID] = None

    # Payload (serialized; protocol never inspects internals)
    payload: Dict[str, Any] = Field(default_factory=dict)

    # Cryptographic identity (computed once at creation, never recomputed)
    leaf_hash: Optional[str] = None


class CognitiveEdge(BaseModel):
    """A typed, directed edge between cognitive nodes.

    Edges carry semantic meaning (CONTAINS, PRECEDES, REFERENCES, etc.)
    and are typed by both the edge itself and the nodes it connects.
    """
    edge_id: UUID = Field(default_factory=uuid4)
    edge_type: str
    source_node_id: UUID
    target_node_id: UUID
    source_type: str = ""
    target_type: str = ""
    weight: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
