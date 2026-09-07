""" Thermal
GitHub: https://github.com/lorenzozanizz/bl-thermal

Version: 1.0.0
Blender: 4.x
License: MIT
"""

bl_info = {
    "name": "Thermal",
    "author": "lorenzozanizz",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "Sidebar > Thermography",
    "description": "An extension to synthetically generate thermal imaging data in Blender",
    "category": "Physics",
}


import sys


# Do not register the BPY module if we are testing
if 'pytest' not in sys.modules:

    from .ui import properties as addon_properties

    from .shaders import classes as shader_classes
    from .ui import classes as ui_classes
    from .operators import classes as operator_classes

    import bpy

    # Transfer parameter groups register first because ThermalRenderSettings holds a
    # PointerProperty to RBFOTransferProperties and cannot precede it.
    registration_classes = (
        *shader_classes,
        *ui_classes,
        *operator_classes,
    )


    # Flatten all PropertyRegistration declarations across modules
    properties = tuple(
        addon_properties
    )


def register():
    """ Register the classes and properties for the GUI extension
    """

    # Register all the required classes
    for cls in registration_classes:
        bpy.utils.register_class(cls)

    # Define all the attributes for the GUI, each on its declared owner
    # (bpy.types.Object, bpy.types.Collection, bpy.types.Scene, ...)
    for reg in properties:
        setattr(reg.owner, reg.name, reg.value)


def unregister():
    """ Unregister the classes and properties for the GUI extension
    """
    import bpy

    # Delete all registered properties in the environment
    for reg in properties:
        delattr(reg.owner, reg.name)

    # Unregister all previously registered classes
    for cls in reversed(registration_classes):
        bpy.utils.unregister_class(cls)

    from .ui.color_bar_gpu import left_bottom_color_bar
    from .ui.gradient_gpu import gradient_overlay
    left_bottom_color_bar.hide()
    gradient_overlay.hide()