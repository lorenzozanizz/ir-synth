
import sys
import types

if "bpy" not in sys.modules:

    bpy = types.ModuleType("bpy")
    bpy_types = types.ModuleType("bpy.types")
    bpy_props = types.ModuleType("bpy.props")
    bpy_utils = types.ModuleType("bpy.utils")
    gpu_extras_batch = types.ModuleType("gpu_extras.batch")

    gpu = types.ModuleType("gpu")
    blf = types.ModuleType("blf")
    gpu_shader = types.ModuleType("gpu.shader")

    class PropertyGroup:
        pass

    class Operator:
        pass

    class Panel:
        pass


    class NodeTree:
        pass

    class ID:
        pass

    class Object(ID):
        pass

    class Collection(ID):
        pass

    class Scene(ID):
        pass

    class UILayout:
        pass

    class Material:
        pass

    class NodeSocket:
        pass

    class ColorRamp:
        pass

    class Context:

        class Scene:

            class ThermalEnvironment:

                factors = []
            thermal_environment = ThermalEnvironment()
        scene = Scene()

    class ShaderNodeTree:
        pass

    class Node:
        pass

    class Menu:
        pass

    for cls in (PropertyGroup, Operator, Panel, NodeTree, ID, Object,
                Collection, Scene, UILayout, Context, Material, ColorRamp, NodeSocket,
                ShaderNodeTree, Node, Menu):
        setattr(bpy_types, cls.__name__, cls)

    def _nop_property(*args, **kwargs):
        return None

    def _batch_for_shader(*args, **kwargs):
        pass

    def _from_builtin(*args, **kwargs):
        pass

    for name in ():
        setattr(gpu_extras_batch, name, _nop_property)

    gpu_extras_batch.batch_for_shader = _batch_for_shader

    for name in ("PointerProperty", "StringProperty", "BoolProperty",
                 "IntProperty", "FloatProperty", "EnumProperty",
                 "CollectionProperty", "FloatVectorProperty"):
        setattr(bpy_props, name, _nop_property)

    blf.size = lambda *args, **kwargs: None
    blf.position = lambda *args, **kwargs: None
    blf.color = lambda *args, **kwargs: None
    blf.draw = lambda *args, **kwargs: None

    bpy_utils.register_class = lambda cls: None
    bpy_utils.unregister_class = lambda cls: None
    gpu_shader.from_builtin = _from_builtin

    bpy.context = Context
    bpy.types = bpy_types
    bpy.props = bpy_props
    bpy.utils = bpy_utils


    gpu.shader = gpu_shader

    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy_types
    sys.modules["bpy.props"] = bpy_props
    sys.modules["bpy.utils"] = bpy_utils
    sys.modules["gpu_extras.batch"] = gpu_extras_batch
    sys.modules["gpu.shader"] = gpu_shader
    sys.modules["gpu"] = gpu
    sys.modules["blf"] = blf


    class Vector:
        pass

    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = Vector
    sys.modules["mathutils"] = mathutils

def foo():
    pass

