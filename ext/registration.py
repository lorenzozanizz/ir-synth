""" Shared registration descriptor. """

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PropertyRegistration:
    """ Describes a single bpy property to attach during registration.

    :param owner: the bpy.types.ID subclass the property is attached to
    :param name: attribute name the property will be accessible under
    :param value: the return value
    """
    owner: Any
    name: str
    value: Any
