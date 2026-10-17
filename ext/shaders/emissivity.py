"""
Emissivity: mixing a surface's own emission with what it reflects.

A real surface radiates only a fraction of a blackbody's output. That
fraction is its emissivity, and the remainder is reflected from the
surroundings, so a camera sees (approximately):

    S_apparent = eps * S(T_surface) + (1 - eps) * S(T_reflected)
"""

from typing import Tuple, Type

from bpy.types import NodeSocket, PropertyGroup, ShaderNodeTree

from ..constants import EMISSIVITY_ATTR_NAME
from .nodes import TreeUtils, MathCompositor
from .transfer import TransferDescriptor


def build_emissivity_socket(
    tree: ShaderNodeTree, location: Tuple[float, float],
) -> NodeSocket:
    """ Return the socket supplying the per-vertex emissivity.

    An Attribute node reading the baked emissivity map. A mesh without the
    attribute reads 0.0 here (a perfect mirror), so every rendered object
    must be baked; VisualizeTemperatureOperator warns when one is not.
    """
    return TreeUtils.new_attribute(tree, EMISSIVITY_ATTR_NAME, location)


def build_emissivity_mix(
    tree: ShaderNodeTree,
    surface_signal: NodeSocket,
    reflected_signal: NodeSocket,
    emissivity: NodeSocket,
    location: Tuple[float, float],
) -> NodeSocket:
    """ Combine the two signals by emissivity and return the result socket.

    Built from Math nodes rather than a Mix node: Mix exposes several
    identically named A/B sockets, one per data type, so it can only be wired
    by index.
    """
    x, y = location
    stride_x, stride_y = MathCompositor.strides()

    weighted_surface = TreeUtils.new_math(
        tree, 'MULTIPLY', (x, y), emissivity, surface_signal, "eps * S_surface",
    )
    one_minus_eps = TreeUtils.new_math(
        tree, 'SUBTRACT', (x, y + stride_y), 1.0, emissivity, "1 - eps",
    )
    weighted_reflected = TreeUtils.new_math(
        tree, 'MULTIPLY', (x + stride_x, y + stride_y),
        one_minus_eps, reflected_signal, "(1 - eps) * S_reflected",
    )
    return TreeUtils.new_math(
        tree, 'ADD', (x + 2 * stride_x, y),
        weighted_surface, weighted_reflected, "S_apparent",
    )


def build_apparent_signal(
    tree: ShaderNodeTree,
    descriptor: Type[TransferDescriptor],
    transfer_props: PropertyGroup,
    settings: PropertyGroup,
    temperature_socket: NodeSocket,
    location: Tuple[float, float],
) -> NodeSocket:
    """ Run the transfer on the surface and on the environment, mix the two by
    emissivity, and return the apparent-signal socket.

    :param descriptor: transfer to apply, used for both branches.
    :param transfer_props: that transfer's parameter group.
    :param settings: the scene's ThermalRenderSettings.
    :param temperature_socket: socket supplying surface Kelvin.
    :param location: top-left of the generated block.
    """
    x, y = location
    stride_x, stride_y = MathCompositor.strides()
    surface_signal = descriptor.build_nodes(
        tree, temperature_socket, transfer_props, (x, y),
    )

    reflected_temperature = TreeUtils.new_value(
        tree,
        settings.reflected_temperature_k(),
        (x - stride_x, y + stride_y),
        label="Reflected T (K)",
    )
    reflected_signal = descriptor.build_nodes(
        tree, reflected_temperature, transfer_props, (x, y + stride_y),
    )

    emissivity = build_emissivity_socket(tree, (x - stride_x, y + 2 * stride_y))

    # Place the mix past whichever branch ended furthest right, so it stays
    # correct regardless of how many nodes the transfer used.
    mix_x = max(
        surface_signal.node.location[0], reflected_signal.node.location[0],
    ) + stride_x
    return build_emissivity_mix(
        tree, surface_signal, reflected_signal, emissivity, (mix_x, y),
    )
