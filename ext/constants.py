""" A module containing thermal constants which
are shared among components in the entire project.
"""

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
