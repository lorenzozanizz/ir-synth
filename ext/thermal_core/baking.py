""" This is the bpy-free counterpart to ui/init_registry.py.
This registry maps a spec class to the numeric evaluate() behaviour that turns
it into actual per-vertex values.

Anything requiring bpy (vertex count, named vertex-group weights, ...) is extracted by
the caller into a BakeInputs before reaching this module.
"""

from typing import Callable, Dict, Type

import numpy as np

from .field import MeshSample
from .specs import (
    AmbientTempSpec, GradientTempSpec, SpecBase, UniformTempSpec, WeightPaintedTempSpec,
    UniformEmissivitySpec, WeightPaintedEmissivitySpec,
)


# Typing hint
# A function which gets evaluated for a temperature initialization
# specification and produces the correct mesh temperature field
EvaluateFn = Callable[[SpecBase, MeshSample], np.ndarray]


class BakeStrategyRegistry:
    """ Maps a spec subclass (TempInitSpec or EmissivitySpec) to the pure
    function that evaluates it into a per-vertex float64 array.

    Adding a new strategy's numeric side means: (1) a dataclass in specs.py,
    (2) one @register(SpecType) function
    here. Callers never branch on spec type directly - always through
    evaluate().
    """

    _REGISTRY: Dict[Type[SpecBase], EvaluateFn] = {}

    @classmethod
    def register(cls, spec_type: Type[SpecBase]):
        def decorator(fn: EvaluateFn) -> EvaluateFn:
            cls._REGISTRY[spec_type] = fn
            return fn
        return decorator

    @classmethod
    def evaluate(cls, spec: SpecBase, sample: MeshSample) -> np.ndarray:
        """ Evaluate spec into a (sample.vertex_count,) float64 array. The
        unit depends on the spec family (Kelvin or emissivity).

        :param spec: resolved, already-validated spec (see
            ui/resolution.py:SpecsResolver.resolve_object_spec).
        :param sample: geometry extracted from bpy by the caller.
        :raises NotImplementedError: spec's type has no evaluator registered
            yet (e.g. a future GradientTempSpec/AmbientTempSpec).
        """
        try:
            fn = cls._REGISTRY[type(spec)]
        except KeyError:
            raise NotImplementedError(
                f"{type(spec).__name__!r} has no BakeStrategyRegistry "
                f"evaluator registered yet."
            ) from None

        values = fn(spec, sample)
        if values.shape != (sample.vertex_count,):
            raise ValueError(
                f"The evaluator for {type(spec).__name__} returned an array of "
                f"shape {values.shape}, expected ({sample.vertex_count},)"
            )
        return values


# Type hint
# A function which re-parametrizes the 0-1 weights falloff in some way, ensuring
# the range is still [0, 1]
FalloffStrategy = Callable[[np.ndarray], np.ndarray]

class FalloffFunctions:

    @staticmethod
    def _smoothstep(t: np.ndarray) -> np.ndarray:
        """ Classic 3t^2 - 2t^3 smoothstep. """
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def evaluate(weights: np.ndarray, falloff_type: str) -> np.ndarray:
        """

        :param weights:
        :param falloff_type:
        :return:
        """
        eval_fn = {
            "LINEAR": lambda t: t,
            "EASE_IN_OUT": FalloffFunctions._smoothstep,
        }.get(falloff_type, lambda t: t)
        return eval_fn(weights)


def _remap_weights(
    weights: np.ndarray, low: float, high: float, falloff: str,
) -> np.ndarray:
    """ Remap 0-1 vertex-group weights onto [low, high] through a falloff.
    Shared by the temperature and the emissivity weight-painted strategies.
    """
    t = FalloffFunctions.evaluate(np.clip(weights, 0.0, 1.0), falloff)
    return low + t * (high - low)


@BakeStrategyRegistry.register(UniformTempSpec)
def _evaluate_uniform(spec: UniformTempSpec, sample: MeshSample) -> np.ndarray:
    """ Every vertex gets the same value; no geometry is consulted. """
    return np.full(sample.vertex_count, spec.value_k, dtype=np.float64)


@BakeStrategyRegistry.register(AmbientTempSpec)
def _evaluate_ambient(spec: AmbientTempSpec, sample: MeshSample) -> np.ndarray:
    """ Every vertex on every object gets the same ambient value; like
    UniformTempSpec, no geometry is consulted. """
    return np.full(sample.vertex_count, spec.value_k, dtype=np.float64)


@BakeStrategyRegistry.register(GradientTempSpec)
def _evaluate_gradient(spec: GradientTempSpec, sample: MeshSample) -> np.ndarray:
    """ Projects each vertex onto the (point_a -> point_b) axis and linearly
    interpolates value_a_k -> value_b_k along it. Vertices projecting outside
    the segment are clamped to the nearest endpoint's value.

    :raises ValueError: point_a and point_b coincide (degenerate axis).
    """
    point_a = np.asarray(spec.point_a, dtype=np.float64)
    axis = np.asarray(spec.point_b, dtype=np.float64) - point_a
    axis_length_sq = float(np.dot(axis, axis))
    if axis_length_sq == 0.0:
        raise ValueError("GradientTempSpec has a degenerate axis (point_a == point_b)")

    # t=0 at point_a, t=1 at point_b; clamped so vertices beyond either
    # endpoint hold that endpoint's value instead of extrapolating.
    t = np.clip((sample.positions - point_a) @ axis / axis_length_sq, 0.0, 1.0)
    return spec.value_a_k + t * (spec.value_b_k - spec.value_a_k)


@BakeStrategyRegistry.register(WeightPaintedTempSpec)
def _evaluate_weight_painted(spec: WeightPaintedTempSpec, sample: MeshSample) -> np.ndarray:
    """ Remaps sample.vertex_group_weights (0-1) onto [spec.min_k, spec.max_k]
    through the specified falloff function spec.falloff.

    :raises ValueError: vertex_group_weights is missing
    """
    weights = sample.vertex_group_weights
    if weights is None:
        raise ValueError(
            "WeightPaintedTempSpec requires MeshSample.vertex_group_weights, "
            "got None - the caller must extract the named vertex group's "
            "weights before calling evaluate()."
        )

    # MeshSample.validate() has already checked the length, so the only
    # remaining job is the remap itself.
    return _remap_weights(weights, spec.min_k, spec.max_k, spec.falloff)


@BakeStrategyRegistry.register(UniformEmissivitySpec)
def _evaluate_uniform_emissivity(spec: UniformEmissivitySpec, sample: MeshSample) -> np.ndarray:
    """ Every vertex gets the same emissivity; no geometry is consulted. """
    return np.full(sample.vertex_count, spec.value, dtype=np.float64)


@BakeStrategyRegistry.register(WeightPaintedEmissivitySpec)
def _evaluate_weight_painted_emissivity(
    spec: WeightPaintedEmissivitySpec, sample: MeshSample,
) -> np.ndarray:
    """ Remaps sample.vertex_group_weights (0-1) onto
    [spec.min_value, spec.max_value] through spec.falloff.

    :raises ValueError: vertex_group_weights is missing
    """
    weights = sample.vertex_group_weights
    if weights is None:
        raise ValueError(
            "WeightPaintedEmissivitySpec requires MeshSample.vertex_group_weights, "
            "got None - the caller must extract the named vertex group's "
            "weights before calling evaluate()."
        )
    return _remap_weights(weights, spec.min_value, spec.max_value, spec.falloff)
