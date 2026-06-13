"""
Ariadne — Generic Cognitive Node Factory.

One creation path for every cognitive node type. ``create_node`` generalizes
the bespoke ``create_episode_node``: it enforces node-type registration
(governance), validates the payload, computes the content hash and the
position-binding leaf hash, and returns a fully-formed ``CognitiveNode`` ready
for persistence.

This is the extensibility seam: an adopter adds a new node type by registering
a ``NodeTypeDefinition`` (``register_node_type``) and passing a ``NodePayload``
subclass — they get governed, hash-correct creation for free, without touching
the protocol layer. The factory is extensible on the outside (any registered
type, any payload) and governed on the inside (registration + validation +
canonical hashing happen here, not in adopter code).
"""

from typing import List, Optional
from uuid import UUID

from ariadne.protocol.governance import enforce_node_type_registered
from ariadne.protocol.leaf_hash import compute_leaf_hash_from_node
from ariadne.protocol.node import CognitiveNode, NodePayload
from ariadne.protocol.registry import REGISTRY, NodeTypeDefinition


def create_node(
    node_type: str,
    *,
    agent_id: str,
    sequence_index: int,
    payload: NodePayload,
    parent_node_id: Optional[UUID] = None,
    schema_version: str = "2.0.0",
) -> CognitiveNode:
    """Create a fully-formed ``CognitiveNode`` of any registered type.

    Steps (identical for every node type):
      1. Governance — the node type must be registered (``enforce_node_type_registered``).
      2. ``payload.validate()`` — payload-specific invariants.
      3. ``content_hash`` — canonical SHA3-256 of the payload.
      4. Build the ``CognitiveNode`` (``tree_leaf_index`` initially equals
         ``sequence_index``; it diverges only on rebalance).
      5. ``leaf_hash`` — the position-binding cryptographic identity.

    Args:
        node_type: Registered cognitive node type (e.g. "episode", "segment").
        agent_id: The authoring agent.
        sequence_index: Immutable position in the agent's cognitive timeline.
        payload: A ``NodePayload`` subclass instance carrying type-specific data.
        parent_node_id: Parent in the cognitive graph (immutable after creation).
        schema_version: Protocol schema version stamped on the node.

    Returns:
        A ``CognitiveNode`` with computed ``content_hash`` and ``leaf_hash``.

    Raises:
        GovernanceViolation: the node type is not registered.
        ValueError: the payload fails its own ``validate()``.
    """
    enforce_node_type_registered(node_type)
    payload.validate()

    content_hash = payload.compute_content_hash()

    node = CognitiveNode(
        node_type=node_type,
        schema_version=schema_version,
        sequence_index=sequence_index,
        tree_leaf_index=sequence_index,
        content_hash=content_hash,
        authored_by=agent_id,
        parent_node_id=parent_node_id,
        payload=payload.to_dict(),
    )

    node.leaf_hash = compute_leaf_hash_from_node(node)
    return node


def register_node_type(
    type_id: str,
    type_name: str,
    *,
    valid_proof_types: Optional[List[str]] = None,
    temporal_profile: str = "bounded",
    schema_extension: Optional[str] = None,
) -> NodeTypeDefinition:
    """Register a new cognitive node type so ``create_node`` will accept it.

    The adopter-facing extensibility hook. After registration, creating nodes of
    ``type_id`` goes through the same governed factory path as built-in types.

    Returns the registered ``NodeTypeDefinition``.
    """
    defn = NodeTypeDefinition(
        type_id=type_id,
        type_name=type_name,
        valid_proof_types=valid_proof_types or [],
        temporal_profile=temporal_profile,
        schema_extension=schema_extension,
    )
    REGISTRY.register(defn)
    return defn
