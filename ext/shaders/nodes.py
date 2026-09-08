"""
Small helpers for building shader node graphs.

Shared by transfer.py and emissivity.py so neither has to repeat the
create-node/set-input/link dance.
"""

from typing import Tuple, Union

from bpy.types import Node, NodeSocket, ShaderNodeTree

# type hint
# Either a literal value or a socket to link from.
Operand = Union[float, NodeSocket]

class TreeUtils:
    """ A set of utility functions to manipulate and generate
    math compositor trees. """


    @staticmethod
    def feed(tree: ShaderNodeTree, socket_input, operand: Operand) -> None:
        """ Drive a node input, either by linking a socket or setting a constant. """
        if isinstance(operand, NodeSocket):
            tree.links.new(operand, socket_input)
        else:
            socket_input.default_value = operand

    @staticmethod
    def new_math(
        tree: ShaderNodeTree,
        operation: str,
        location: Tuple[float, float],
        first: Operand,
        second: Operand = None,
        label: str = "",
    ) -> NodeSocket:
        """ Add one Math node and return its output socket.

        :param operation: ShaderNodeMath operation, e.g. 'MULTIPLY'.
        :param first: input 0.
        :param second: input 1, or None for unary operations like 'EXPONENT'.
        """
        node: Node = tree.nodes.new('ShaderNodeMath')
        node.operation = operation
        node.location = location
        node.label = label

        TreeUtils.feed(tree, node.inputs[0], first)
        if second is not None:
            TreeUtils.feed(tree, node.inputs[1], second)
        return node.outputs[0]

    @staticmethod
    def new_value(
        tree: ShaderNodeTree, value: float, location: Tuple[float, float], label: str = "",
    ) -> NodeSocket:
        """ Add a Value node holding a constant and return its output socket. """
        node: Node = tree.nodes.new('ShaderNodeValue')
        node.location = location
        node.label = label
        node.outputs[0].default_value = value
        return node.outputs[0]

    @staticmethod
    def new_attribute(
        tree: ShaderNodeTree, attribute_name: str, location: Tuple[float, float],
    ) -> NodeSocket:
        """ Add a geometry Attribute node and return its scalar output. """
        node: Node = tree.nodes.new('ShaderNodeAttribute')
        node.attribute_type = 'GEOMETRY'
        node.attribute_name = attribute_name
        node.location = location
        node.label = attribute_name
        return node.outputs['Fac']


class MathCompositor:
    """ Appends Math nodes left to right, tracking position and current output.

    For straight-line expressions. Branching graphs should call new_math()
    directly.
    """

    # Horizontal spacing between generated nodes.
    NODE_STRIDE_X = 180.0
    NODE_STRIDE_Y = 300.0

    def __init__(self, tree: ShaderNodeTree, location: Tuple[float, float], socket: NodeSocket):
        self._tree = tree
        self._x, self._y = location
        self.socket = socket

    def step(
        self, operation: str, operand: Operand, socket_index: int = 1, label: str = "",
    ) -> NodeSocket:
        """ Add a Math node consuming the current socket.

        :param socket_index: which input the current socket occupies, so
            non-commutative operations read in the intended order.
        """
        first, second = (
            (self.socket, operand) if socket_index == 0 else (operand, self.socket)
        )
        self.socket = TreeUtils.new_math(
            self._tree, operation, (self._x, self._y), first, second, label
        )
        self._x += MathCompositor.NODE_STRIDE_X
        return self.socket

    def step_unary(self, operation: str, label: str = "") -> NodeSocket:
        """ Add a single-input Math node, which reads input 0 only. """
        self.socket = TreeUtils.new_math(
            self._tree, operation, (self._x, self._y), self.socket, None, label
        )
        self._x += MathCompositor.NODE_STRIDE_X
        return self.socket

    @property
    def location(self) -> Tuple[float, float]:
        """ Where the next node would be placed. """
        return self._x, self._y

    @staticmethod
    def strides() -> tuple[float, float]:
        """ Get the strides used to visualize the built node tree """
        return MathCompositor.NODE_STRIDE_X, MathCompositor.NODE_STRIDE_Y
