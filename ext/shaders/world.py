"""
The World for the ray-traced path: what a ray sees when it hits no mesh.

A ray that leaves the scene returns the signal of the background temperature,
which is the scene's Ambient Temperature factor. Surfaces that face empty
space reflect it through their (1 - eps) term; pixels that see no object show
it directly.

The World uses the same transfer as the materials, and, like them, without the
detector offset O: the World is a source of light transport too.
"""

from typing import Tuple, Type, Any

from bpy.types import Node, PropertyGroup

from .nodes import MathCompositor, TreeUtils
from .transfer import TransferDescriptor

_VALUE_LOCATION: Tuple[float, float] = (-1200.0, 0.0)


def build_thermal_world(
    world: Any,
    descriptor: Type[TransferDescriptor],
    props: PropertyGroup,
    background_k: float,
) -> None:
    """ Rebuild world's node tree as a uniform thermal background.

    :param world: the World to rebuild. Its node tree is cleared.
    :param descriptor: transfer to apply, the same one the materials use.
    :param props: that transfer's parameter group.
    :param background_k: background temperature in Kelvin.
    """
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    x_stride, _ = MathCompositor.strides()

    temperature = TreeUtils.new_value(
        tree, background_k, _VALUE_LOCATION, label="Background T (K)",
    )
    signal = descriptor.build_nodes(
        tree, temperature, props,
        (_VALUE_LOCATION[0] + x_stride, _VALUE_LOCATION[1]),
        with_offset=False,
    )
    x = signal.node.location[0] + x_stride

    background: Node = tree.nodes.new('ShaderNodeBackground')
    background.location = (x, _VALUE_LOCATION[1])
    background.inputs['Strength'].default_value = 1.0
    # A float linked into a colour socket broadcasts to (v, v, v).
    tree.links.new(signal, background.inputs['Color'])

    output: Node = tree.nodes.new('ShaderNodeOutputWorld')
    output.location = (x + x_stride, _VALUE_LOCATION[1])
    tree.links.new(background.outputs['Background'], output.inputs['Surface'])
