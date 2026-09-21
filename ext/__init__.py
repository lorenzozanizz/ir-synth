""" Thermal
GitHub: https://github.com/lorenzozanizz/bl-thermal

Version: 1.0.0
Blender: 4.x
License: MIT
"""

import importlib.util
import sys
from typing import Optional, Tuple

bl_info = {
    "name": "Thermal",
    "author": "lorenzozanizz",
    "version": (0, 9, 0),
    "blender": (4, 5, 0),
    "location": "Sidebar > Thermography",
    "description": "An extension to synthetically generate thermal imaging data in Blender",
    "category": "Physics",
}


class BlenderUnavailableError(RuntimeError):
    """ Raised when a bpy-only entry point is called outside Blender """


# Resolved on the first register() call and kept so that unregister() tears
# down exactly what was set up, in reverse. None means "never registered".
_REGISTRATION_CLASSES: Optional[Tuple] = None
_PROPERTIES: Optional[Tuple] = None


def _load_registration_targets() -> Tuple[Tuple, Tuple]:
    """ Import the GUI layers and collect what register() has to install.

    Imported here rather than at module scope to avoid damaging hooks with the
    dependency on BPY.

    :return: (classes to register, PropertyRegistration entries to attach)
    :raises BlenderUnavailableError: bpy is not importable.
    """
    from .ui import properties as addon_properties
    from .shaders import classes as shader_classes
    from .ui import classes as ui_classes
    from .operators import classes as operator_classes

    # Transfer parameter groups register first because ThermalRenderSettings holds a
    # PointerProperty to RBFOTransferProperties and cannot precede it.
    registration_classes = (
        *shader_classes,
        *ui_classes,
        *operator_classes,
    )


    # Flatten all PropertyRegistration declarations across modules
    properties = tuple(addon_properties)

    return registration_classes, properties


def register():
    """ Register the classes and properties for the GUI extension
    """
    global _REGISTRATION_CLASSES, _PROPERTIES

    # Resolved first: it raises BlenderUnavailableError with an explanation,
    # which is more useful
    _REGISTRATION_CLASSES, _PROPERTIES = _load_registration_targets()

    import bpy

    # Register all the required classes
    for cls in _REGISTRATION_CLASSES:
        bpy.utils.register_class(cls)

    # Define all the attributes for the GUI, each on its declared owner
    # (bpy.types.Object, bpy.types.Collection, bpy.types.Scene, ...)
    for reg in _PROPERTIES:
        setattr(reg.owner, reg.name, reg.value)


def unregister():
    """ Unregister the classes and properties for the GUI extension
    """
    global _REGISTRATION_CLASSES, _PROPERTIES

    if _REGISTRATION_CLASSES is None or _PROPERTIES is None:
        return

    import bpy

    # Delete all registered properties in the environment
    for reg in _PROPERTIES:
        delattr(reg.owner, reg.name)

    # Unregister all previously registered classes
    for cls in reversed(_REGISTRATION_CLASSES):
        bpy.utils.unregister_class(cls)

    _REGISTRATION_CLASSES = None
    _PROPERTIES = None

    from .ui.color_bar_gpu import left_bottom_color_bar
    from .ui.gradient_gpu import gradient_overlay
    left_bottom_color_bar.hide()
    gradient_overlay.hide()
