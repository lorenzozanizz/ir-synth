""" A module containing thermal constants which
are shared among components in the entire project.
"""

from dataclasses import dataclass

MAIN_PANEL_NAME = "Thermography"
VERSION = "0.9.0"
TARGET_VERSION = "4.5.0"

REPO_URL = "https://github.com/lorenzozanizz/bl-thermal"
DOCU_URL = "https://github.com/lorenzozanizz/bl-thermal"


# ( Single source of truth for the per-vertex float temperature field. Kept here
# to be accessible to both UI and backend
TEMPERATURE_ATTR_NAME = "thermal_temperature_k"
TEMPERATURE_ATTR_TYPE = 'FLOAT'
TEMPERATURE_ATTR_DOMAIN = 'POINT'


@dataclass(frozen=True)
class MeshAttribute:
    """ The name, data type and domain of one per-vertex mesh attribute that
    the bake writes and the shaders read.
    """
    # attribute name on the mesh
    name: str
    # Blender attribute data type
    data_type: str = 'FLOAT'
    # Blender attribute domain
    domain: str = 'POINT'


# ( The per-vertex temperature field, in Kelvin )
TEMPERATURE_ATTR = MeshAttribute(
    TEMPERATURE_ATTR_NAME, TEMPERATURE_ATTR_TYPE, TEMPERATURE_ATTR_DOMAIN,
)

# ( The per-vertex emissivity map, a value in [0, 1]. Every baked mesh must
#   have it: a shader Attribute node reads a missing attribute as 0.0, which
#   is a perfect mirror and not a safe default )
EMISSIVITY_ATTR_NAME = "thermal_emissivity"
EMISSIVITY_ATTR = MeshAttribute(EMISSIVITY_ATTR_NAME)

# ------------- Temperature visualization material ---------------
# |
# ( Name of the single shared material VisualizeTemperatureOperator builds
#   and assigns to every baked object )
TEMPERATURE_MATERIAL_NAME = "Thermal Visualization"

DEFAULT_HEAT_PALETTE = (
    (0.0, 0.0, 0.6, 1.0),  # coldest: deep blue
    (0.0, 0.8, 0.8, 1.0),  # cool: cyan
    (1.0, 0.9, 0.0, 1.0),  # warm: yellow
    (0.8, 0.0, 0.0, 1.0),  # hottest: red
)


# Version of the dictionary layout produced by serialization schemas used for
# hooks
#
# Written into every serialized config and checked on the way back in.
SCHEMA_VERSION = 1

# Versions this build can still read.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# The key the version is stored under.
SCHEMA_VERSION_KEY = "schema_version"

