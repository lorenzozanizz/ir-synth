"""
Surface shader for the ray-traced path: a surface that emits and reflects.

"""

from typing import Tuple

from bpy.types import Node, NodeSocket, PropertyGroup, ShaderNodeTree

from .nodes import TreeUtils, MathCompositor


def build_reflective_surface(
    tree: ShaderNodeTree,
    surface_signal: NodeSocket,
    emissivity: NodeSocket,
    settings: PropertyGroup,
    location: Tuple[float, float],
) -> NodeSocket:
    """ Build Emission + (Diffuse/Glossy mix) and return the shader socket.

    :param surface_signal: socket carrying S(T) - O for the surface.
    :param emissivity: socket carrying the per-vertex emissivity.
    :param settings: the scene's ThermalRenderSettings (specular_fraction,
        reflection_roughness).
    :param location: top-left of the generated block.
    """
    x, y = location
    stride_x, stride_y = MathCompositor.strides()

    # Own radiation: eps * S. A float linked into a colour socket broadcasts
    # to (v, v, v).
    emitted = TreeUtils.new_math(
        tree, 'MULTIPLY', (x, y), emissivity, surface_signal, "eps * S",
    )
    emission: Node = tree.nodes.new('ShaderNodeEmission')
    emission.location = (x + stride_x, y)
    emission.inputs['Strength'].default_value = 1.0
    tree.links.new(emitted, emission.inputs['Color'])

    # Reflection: albedo 1 - eps on both lobes.
    reflectance = TreeUtils.new_math(
        tree, 'SUBTRACT', (x, y + stride_y), 1.0, emissivity, "1 - eps",
    )
    diffuse: Node = tree.nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.location = (x + stride_x, y + stride_y)
    tree.links.new(reflectance, diffuse.inputs['Color'])

    glossy: Node = tree.nodes.new('ShaderNodeBsdfGlossy')
    glossy.location = (x + stride_x, y + 2 * stride_y)
    glossy.distribution = 'MULTI_GGX'
    glossy.inputs['Roughness'].default_value = settings.reflection_roughness
    tree.links.new(reflectance, glossy.inputs['Color'])

    # Mix Shader has two inputs named "Shader", so wire by index:
    # 0 = Fac, 1 = first shader (Fac = 0), 2 = second shader (Fac = 1).
    mix: Node = tree.nodes.new('ShaderNodeMixShader')
    mix.location = (x + 2 * stride_x, y + stride_y)
    mix.label = "Specular fraction"
    mix.inputs[0].default_value = settings.specular_fraction
    tree.links.new(diffuse.outputs['BSDF'], mix.inputs[1])
    tree.links.new(glossy.outputs['BSDF'], mix.inputs[2])

    add: Node = tree.nodes.new('ShaderNodeAddShader')
    add.location = (x + 3 * stride_x, y)
    add.label = "Emit + Reflect"
    tree.links.new(emission.outputs['Emission'], add.inputs[0])
    tree.links.new(mix.outputs['Shader'], add.inputs[1])
    return add.outputs['Shader']
