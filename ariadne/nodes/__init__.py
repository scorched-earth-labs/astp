"""
Ariadne Node Types — domain-specific extensions of CognitiveNode.

Each node type implements NodePayload and registers with the
NodeTypeRegistry. The protocol layer never imports from here.

``create_node`` is the generic, governed factory for every registered type;
``register_node_type`` is the extensibility hook for adopter-defined types.
"""

from ariadne.nodes.factory import create_node, register_node_type

__all__ = ["create_node", "register_node_type"]
