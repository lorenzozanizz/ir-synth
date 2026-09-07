"""
Builds the shader node graph for visualizing the temperature field
over the scene: reads a baked per-vertex float attribute and turns it
into material color, entirely with nodes.

Graph: Attribute -> Map Range -> Color Ramp -> Emission -> Material Output.
"""

from bpy.types import Material, ColorRamp


def build_temperature_node_graph(
    material: Material, attribute_name: str, min_value: float, max_value: float,
) -> None:
    """ Clears material's node tree and rebuilds it as the graph described
    above. Idempotent since it always starts from a clean slate rather than
    patching an existing graph.

    :param material: material to build. use_nodes is turned on if not
        already.
    :param attribute_name: name of the per-vertex/point float attribute to
        read
    :param min_value: attribute value that maps to the cold end of the
        palette
    :param max_value: attribute value that maps to the hot end of the
        palette
    """
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()

    attribute_node = tree.nodes.new('ShaderNodeAttribute')
    attribute_node.attribute_type = 'GEOMETRY'
    attribute_node.attribute_name = attribute_name
    attribute_node.location = (-800, 0)

    map_range = tree.nodes.new('ShaderNodeMapRange')
    map_range.clamp = True
    map_range.inputs['From Min'].default_value = min_value
    map_range.inputs['From Max'].default_value = max_value
    map_range.inputs['To Min'].default_value = 0.0
    map_range.inputs['To Max'].default_value = 1.0
    map_range.location = (-550, 0)

    color_ramp_node = tree.nodes.new('ShaderNodeValToRGB')
    color_ramp_node.location = (-300, 0)
    _apply_thermal_palette(color_ramp_node.color_ramp)

    emission = tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1.0
    emission.location = (-50, 0)

    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.location = (200, 0)

    links = tree.links
    links.new(attribute_node.outputs['Fac'], map_range.inputs['Value'])
    links.new(map_range.outputs['Result'], color_ramp_node.inputs['Fac'])
    links.new(color_ramp_node.outputs['Color'], emission.inputs['Color'])
    links.new(emission.outputs['Emission'], output.inputs['Surface'])


def _apply_thermal_palette(color_ramp: ColorRamp) -> None:
    """ Overwrites color_ramp's stops with a cold(blue)->hot(red) palette.
    """
    stops = (
        (0.00, (0.0, 0.0, 0.6, 1.0)),   # coldest - deep blue
        (0.33, (0.0, 0.8, 0.8, 1.0)),   # cool - cyan
        (0.66, (1.0, 0.9, 0.0, 1.0)),   # warm - yellow
        (1.00, (0.8, 0.0, 0.0, 1.0)),   # hottest - red
    )
    elements = color_ramp.elements
    elements[0].position, elements[0].color = stops[0]
    elements[-1].position, elements[-1].color = stops[-1]
    for position, color in stops[1:-1]:
        elements.new(position).color = color
