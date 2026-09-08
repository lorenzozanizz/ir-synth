"""
Blender-UI side PropertyGroups mirroring the transfer specs in
thermal_core/radiometry.py.

These hold live UI state. TransferDescriptor.build_spec() converts them into
the pure dataclasses before a node graph or a numpy evaluation.
"""

from bpy.types import PropertyGroup
from bpy.props import FloatProperty


class RBFOTransferProperties(PropertyGroup):
    """ UI state for TransferType.RBFO: S = R / (exp(B/T) - F) + O.
    """
    r: FloatProperty(                                                   # type: ignore
        name="R",
        description="Scaling coefficient, absorbing the physical constants, "
                    "band width and detector gain",
        default=120.0,
    )
    b: FloatProperty(                                                   # type: ignore
        name="B",
        description="Exponential coefficient in Kelvin, h*c/(lambda_c*k). "
                    "Around 1439 for a 10um band centre",
        default=1438.8,
        min=1e-6,
    )
    f: FloatProperty(                                                   # type: ignore
        name="F",
        description="Shape correction for the band not being infinitely "
                    "narrow. Real cameras report values near 1",
        default=1.0,
    )
    o: FloatProperty(                                                   # type: ignore
        name="O",
        description="Additive detector offset",
        default=0.0,
    )


class WienTransferProperties(PropertyGroup):
    """ UI state for TransferType.WIEN: S = R * exp(-B/T) + O.
    """
    r: FloatProperty(                                                   # type: ignore
        name="R",
        description="Scaling coefficient, absorbing the physical constants, "
                    "band width and detector gain",
        default=120.0,
    )
    b: FloatProperty(                                                   # type: ignore
        name="B",
        description="Exponential coefficient in Kelvin, h*c/(lambda_c*k). "
                    "Around 1439 for a 10um band centre",
        default=1438.8,
        min=1e-6,
    )
    o: FloatProperty(                                                   # type: ignore
        name="O",
        description="Additive detector offset",
        default=0.0,
    )