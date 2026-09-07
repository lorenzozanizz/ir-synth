"""
Pure numeric radiometric transfer from surface temperature to signal.

A transfer is a pointwise scalar function carrying no notion of geometry,
visibility or light transport, as the reflected component of thermal
imaging is handled downstream in the shader.

1. The shader rebuilds the transfer as a Cycles node chain so it evaluates
    on the GPU per shading point.
2. This module evaluates it on numpy arrays, which is what lets the
    visualization operator normalize a false-colour palette in signal
    space rather than temperature space.

Both must agree. Any change to an evaluator here has a matching change in the
node builder there.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, Type

import numpy as np

from .contracts import TransferType
# Import the physical constant required:
# second radiation constant, + some configs
from ..physical_constants import *


@dataclass(frozen=True)
class TransferSpec(ABC):
    """ Base class for a single radiometric transfer function.

    Concrete subclasses correspond to each TransferType member. Subclasses
    are frozen dataclasses holding only plain numbers, so they are hashable,
    comparable and safe and cheap to construct  on every bake.
    """

    @property
    @abstractmethod
    def transfer_type(self) -> TransferType:
        """ The TransferType this spec implements. """
        raise NotImplementedError

    def validate(self) -> None:
        """ Raise ValueError if the spec's parameters are physically or
        numerically invalid.
        """
        pass

    def valid_temperature_range(self) -> Tuple[float, Optional[float]]:
        """ The Kelvin interval over which this spec is numerically safe to
        evaluate, as (low, high). A high of None means unbounded above.

        The rationale of this is that certain approximations for the transfer are
        only valid or feasible for a certain range of temperatures in standard
        conditions, and fail otherwise.
        """
        return MIN_TRANSFER_TEMPERATURE_K, None

    def validate_over(self, temperatures_k: np.ndarray) -> None:
        """ Raise ValueError if any temperature in temperatures_k falls
        outside valid_temperature_range().

        :param temperatures_k: per-vertex Kelvin values, any shape.
        """
        low, high = self.valid_temperature_range()
        # Cant compute min or max on empty meshes, bugfixed
        if temperatures_k.size <= 0:
            return
        observed_min = float(np.min(temperatures_k))
        observed_max = float(np.max(temperatures_k))

        if observed_min < low:
            raise ValueError(
                f"{type(self).__name__} is only valid at or above {low}K, but "
                f"the scene contains {observed_min}K."
            )
        if high is not None and observed_max > high:
            raise ValueError(
                f"{type(self).__name__} becomes singular above {high:.1f}K, but "
                f"the scene contains {observed_max:.1f}K. Adjust the transfer "
                f"parameters or the scene's temperatures."
            )

    def invert(self, signal: np.ndarray) -> np.ndarray:
        """ Recover Kelvin from a signal value, the inverse of evaluating this
        spec.

        Optional. Needed to label a false-colour legend in physical units once
        the palette has been normalized in signal space; not needed to render.

        :raises NotImplementedError: this spec has no closed-form inverse.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not define an inverse."
        )


@dataclass(frozen=True)
class RBFOTransferSpec(TransferSpec):
    """ Taken from GenICam ICD FLIR AX5 Camera as in
    https://device.report/m/bb0fb3a133c0e28de013f89093d51f0629ef0e14866976b11b9d92bc19177b85.pdf

        S(T) = R / (exp(B / T) - F) + O

    Starting from Planck's law and assuming the band
    is narrow enough to be represented by a single centre wavelength, this
    falls out directly, with B = h*c / (lambda_c * k).
    Because it keeps the exponential instead of approximating it with a power
    law, it stays accurate across a much wider temperature span than a T^n
    fit.

    :param r: scaling coefficient, absorbing the physical constants, the band
        width and the detector gain.
    :param b: exponential coefficient in Kelvin, h*c / (lambda_c * k).
    :param f: shape correction, near 1, for the band not being infinitely
        narrow.
    :param o: additive detector offset (dark signal).
    """
    r: float
    b: float
    f: float
    o: float

    @property
    def transfer_type(self) -> TransferType:
        return TransferType.RBFO

    @staticmethod
    def from_center_wavelength(
        center_wavelength_m: float, r: float = 1.0, f: float = 1.0, o: float = 0.0,
    ) -> "RBFOTransferSpec":
        """ Build a spec deriving b from a band centre wavelength rather than
        stating it directly, for when a sensor band is known but its
        calibration constants are not.

        :param center_wavelength_m: band centre in metres (10micrometers -> 1e-5).
        :param r: scaling coefficient, see class docstring.
        :param f: shape correction, see class docstring.
        :param o: detector offset, see class docstring.
        """
        if center_wavelength_m <= 0.0:
            raise ValueError(
                f"center_wavelength_m must be positive, got {center_wavelength_m}"
            )
        return RBFOTransferSpec(
            # See documentation of physical_constants.py to see what this constant represents
            r=r, b=SECOND_RADIATION_CONSTANT_MK / center_wavelength_m,
            f=f, o=o,
        )

    def validate(self) -> None:
        """ Simple validation steps on the parameters """
        if self.b <= 0.0:
            raise ValueError(f"RBFOTransferSpec.b ({self.b}) must be positive.")
        if self.r == 0.0:
            raise ValueError("RBFOTransferSpec.r is 0, which nullifies all thermal contrast.")

    def valid_temperature_range(self) -> Tuple[float, Optional[float]]:
        """ The denominator exp(B/T) - F vanishes at T = B / ln(F), above
        which the signal changes sign and the model is meaningless.

        exp(B/T) is decreasing in T and tends to 1 from above, so for F <= 1
        the denominator is positive at every temperature and there is no upper
        bound.
        """
        if self.f <= 1.0:
            return MIN_TRANSFER_TEMPERATURE_K, None
        return MIN_TRANSFER_TEMPERATURE_K, self.b / float(np.log(self.f))

    def invert(self, signal: np.ndarray) -> np.ndarray:
        """ T = B / ln(R / (S - O) + F).

        :raises ValueError: signal contains values at or below the offset O,
            which are unreachable outputs of this spec and so have no
            corresponding temperature.
        """
        signal = np.asarray(signal, dtype=np.float64)
        above_offset = signal - self.o
        if np.any(above_offset <= 0.0):
            raise ValueError(
                "Signal values at or below the offset O are not in the range "
                "of this transfer and cannot be inverted."
            )
        return self.b / np.log(self.r / above_offset + self.f)


# Type hint
# A function evaluating one resolved TransferSpec into a signal array of the
# same shape as the Kelvin array handed to it.
TransferFn = Callable[[TransferSpec, np.ndarray], np.ndarray]


class TransferRegistry:
    """ Maps a TransferSpec subclass to the pure function that evaluates it
    into a signal array.

    Keyed on the spec class, exactly as BakeStrategyRegistry is, so callers
    never branch on spec type directly - always through evaluate().
    """

    _REGISTRY: Dict[Type[TransferSpec], TransferFn] = {}

    @classmethod
    def register(cls, spec_type: Type[TransferSpec]):
        def decorator(fn: TransferFn) -> TransferFn:
            cls._REGISTRY[spec_type] = fn
            return fn
        return decorator

    @classmethod
    def evaluate(cls, spec: TransferSpec, temperatures_k: np.ndarray) -> np.ndarray:
        """ Evaluate spec over temperatures_k, returning a float64 signal array
        of the same shape.

        Temperatures are clamped up to MIN_TRANSFER_TEMPERATURE_K first, so a
        stray zero or negative value degrades to the low end of the curve
        instead of producing a division warning or a NaN that would propagate
        silently into a rendered image.

        :param spec: a validated TransferSpec.
        :param temperatures_k: Kelvin values, any shape.
        :raises NotImplementedError: spec's type has no evaluator registered
            yet (e.g. a future PlanckLUTTransferSpec).
        """
        try:
            fn = cls._REGISTRY[type(spec)]
        except KeyError:
            raise NotImplementedError(
                f"{type(spec).__name__!r} has no TransferRegistry evaluator "
                f"registered yet."
            ) from None

        temperatures_k = np.asarray(temperatures_k, dtype=np.float64)
        clamped = np.maximum(temperatures_k, MIN_TRANSFER_TEMPERATURE_K)
        return fn(spec, clamped)

    @classmethod
    def is_implemented(cls, spec_type: Type[TransferSpec]) -> bool:
        """ Whether spec_type has an evaluator, so the UI can offer an
        unimplemented TransferType greyed-out rather than hiding it.
        """
        return spec_type in cls._REGISTRY


def signal_range(spec: TransferSpec, temperatures_k: np.ndarray) -> Tuple[float, float]:
    """ The (min, max) signal produced by spec across temperatures_k.

    A degenerate range (a scene at one uniform temperature) is returned
    without padding or extending the interval artificially.

    :param spec: a validated TransferSpec.
    :param temperatures_k: Kelvin values, any shape.
    """
    signal = TransferRegistry.evaluate(spec, temperatures_k)
    return float(np.min(signal)), float(np.max(signal))


def signal_span(
    spec: TransferSpec, span_min_k: float, span_max_k: float
) -> Tuple[float, float]:
    """ Convert a Kelvin display span into the corresponding signal span.

    Two scalar evaluations, not a survey of the scene: the transfer is
    monotonic, so the endpoints map to the endpoints.

    :raises ValueError: the span is empty or inverted.
    """
    if span_max_k <= span_min_k:
        raise ValueError(
            f"Display span is empty: min ({span_min_k}K) must be below max "
            f"({span_max_k}K)."
        )
    low, high = TransferRegistry.evaluate(spec, np.array([span_min_k, span_max_k]))
    return float(low), float(high)


@TransferRegistry.register(RBFOTransferSpec)
def _evaluate_rbfo(spec: RBFOTransferSpec, temperatures_k: np.ndarray) -> np.ndarray:
    """ S = R / (exp(B/T) - F) + O, evaluated elementwise.

    Overflow is expected and handled implicitly by the fact that 1/inf = 0.
    Letting it happen is cheaper and better-behaved than branching around i
    t, so the warning is suppressed and the result used directly.
    """
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        denominator = np.exp(np.clip(spec.b / temperatures_k, a_max=MAX_EXPONENT_ARGUMENT, a_min=None)) - spec.f
        np.clip(denominator, a_min=UNDERFLOW_GUARD, a_max=None, out=denominator)
        signal = spec.r / denominator + spec.o

    # exp() overflowing to inf leaves R/inf == 0 and signal == O, which is
    # correct.
    # inf - inf, only reachable with a non-finite parameter, leaves a
    # NaN that would otherwise propagate into. For this reason we select the
    # finite vertices and instead use the default value "o"
    return np.where(np.isfinite(signal), signal, spec.o)
