"""
Ariadne Protocol — Cognitive persistence for multi-agent systems.

Bring your own cognitive architecture. Ariadne handles the persistence,
integrity verification, and coordination of agent state transitions.

Core modules:
    ariadne.core.schema         — Episode/Segment/Signal models, governance rules G1-G9
    ariadne.core.merkle         — Adaptive Merkle tree (integrity verification)
    ariadne.core.crystallization — Crystallization delta state machine
    ariadne.core.wil            — Write Intent Log (cross-system write coordination)

Adapters:
    ariadne.adapters.neo4j      — Reference implementation (Neo4j graph database)
"""

__version__ = "0.1.0"
