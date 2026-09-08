""" A module containing definition and resources for several physical constants
which enter when computing sensor models, emittance and emission from the
raw temperature map imposed on the scene as an initial state.
"""

# ------------------------ Physical constants ------------------------

# SECOND RADIATION CONSTANT
# https://physics.nist.gov/cgi-bin/cuu/CCValue?c22ndrc|ShowFirst=Browse
# Second radiation constant c2 = h*c/k, in metre-Kelvin
SECOND_RADIATION_CONSTANT_MK = 1.4387768775e-2

# \cite{waldermar_et_dudzik} taken from the "Symbols" section.
TECHNICAL_CONSTANT_BB_RAD_W_MM2_KM4 = 5.67032

SPEED_OF_LIGHT_VACUUM_M_SM1 = 299792458

# \cite{waldermar_et_dudzik} for this, "Symbols" section
FIRST_RADIATION_CONSTANT_W_M2 = 3.741823e-16

# Temperatures at or below this are clamped before entering any transfer.
# Guards the 1/T division and keeps exp(B/T) from overflowing to inf.
# Simulation would fail for temperatures this low anyway. This avoid numerical
# issues in cases of bad input.
MIN_TRANSFER_TEMPERATURE_K = 1.0

STEFAN_BOLTZMANN_CONSTANT_W_ = 5.67032e-8


# ------------------------ Numerical constants ------------------------

# Maximum exponent computed to avoid overflowing to np.inf
MAX_EXPONENT_ARGUMENT = 80
# Minimum value taken into consideration, any smaller value gets clipped to the guard
UNDERFLOW_GUARD = 1e-6
