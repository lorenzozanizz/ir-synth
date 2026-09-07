"""
Pure numeric evaluation of a FieldOperation against a FieldSet.

This module is the bpy-free equivalent of ui/op_registry.py.
There are two registration decorators, because the two kinds of operation need
different things:

    @OpRegistry.register_per_object(OpType.SMOOTH)
    def _smooth(op, field, sample) -> np.ndarray: ...

        Gets one object at a time.

    @OpRegistry.register_scene(OpType.CONTACT_DIFFUSION)
    def _contact(op, fields) -> None: ...

        Gets the whole FieldSet and mutates it as required by the operation.

Callers only ever go through apply().
"""

from typing import Callable, Dict, Union

import numpy as np

from .baking import FalloffFunctions
from .contracts import OpStage, OpType
from .field import FieldSet, MeshSample, TemperatureField
from .operations import FieldOperation, PerObjectOperation


# type hint
PerObjectFn = Callable[[PerObjectOperation, TemperatureField, MeshSample], np.ndarray]
SceneFn = Callable[[FieldOperation, FieldSet], None]


class OpRegistry:
    """ Maps an OpType to the function that evaluates it. """

    _PER_OBJECT: Dict[OpType, PerObjectFn] = {}
    _SCENE: Dict[OpType, SceneFn] = {}

    @classmethod
    def register_per_object(cls, op_type: OpType):
        def decorator(fn: PerObjectFn) -> PerObjectFn:
            cls._PER_OBJECT[op_type] = fn
            return fn
        return decorator

    @classmethod
    def register_scene(cls, op_type: OpType):
        def decorator(fn: SceneFn) -> SceneFn:
            cls._SCENE[op_type] = fn
            return fn
        return decorator

    @classmethod
    def is_registered(cls, op_type: OpType) -> bool:
        return op_type in cls._PER_OBJECT or op_type in cls._SCENE

    @classmethod
    def apply(cls, operation: FieldOperation, fields: FieldSet) -> None:
        """ Run one operation over the FieldSet, in place.

        This is what gets injected into pipeline.evaluate as apply_operation.

        :raises NotImplementedError: no evaluator is registered for this
            operation's type yet.
        :raises ValueError: an evaluator returned the wrong number of values.
        """
        if not operation.enabled:
            return

        if operation.stage is OpStage.PER_OBJECT:
            cls._apply_per_object(operation, fields)
        else:
            cls._apply_scene(operation, fields)

    @classmethod
    def _apply_per_object(cls, operation: PerObjectOperation, fields: FieldSet) -> None:
        fn = cls._lookup(cls._PER_OBJECT, operation)

        for key in operation.scope.resolve(fields):
            field = fields.field_for(key)
            values = fn(operation, field, fields.sample_for(key))
            # with_values length-checks, so a bad evaluator fails naming itself
            # rather than surfacing later as a foreach_set error in Blender.
            try:
                fields.set_field(key, field.with_values(values))
            except ValueError as error:
                raise ValueError(
                    f"The evaluator for {type(operation).__name__} returned a bad "
                    f"result for {key!r}: {error}"
                ) from error

    @classmethod
    def _apply_scene(cls, operation: FieldOperation, fields: FieldSet) -> None:
        fn = cls._lookup(cls._SCENE, operation)
        fn(operation, fields)

    @staticmethod
    def _lookup(
        table: Union[Dict[OpType, PerObjectFn], Dict[OpType, SceneFn]],
        operation: FieldOperation,
    ):
        try:
            return table[operation.op_type]
        except KeyError:
            raise NotImplementedError(
                f"{type(operation).__name__!r} ({operation.op_type.value}) has no "
                f"{operation.stage.value} evaluator registered in OpRegistry yet."
            ) from None


@OpRegistry.register_per_object(OpType.CLAMP)
def _apply_clamp(operation, field: TemperatureField, sample: MeshSample) -> np.ndarray:
    """ Constrain every value into the operation's bounds. """
    return np.clip(field.values, operation.min_k, operation.max_k)


@OpRegistry.register_per_object(OpType.SMOOTH)
def _apply_smooth(operation, field: TemperatureField, sample: MeshSample) -> np.ndarray:
    """ Laplacian smoothing over the mesh's edges.

    Each pass moves every vertex a fraction of the way toward the mean of its
    edge neighbours. Vertices with no edges keep their value, so a mesh of
    loose points is left alone instead of collapsing to zero.
    """
    values = field.values.copy()
    if operation.iterations == 0 or not sample.has_geometry():
        return values

    offsets, neighbours = sample.adjacency()
    counts = np.diff(offsets)
    connected = counts > 0
    # Which vertex each entry of `neighbours` belongs to, so the per-vertex
    # sums can be accumulated with a single bincount per pass.
    owners = np.repeat(np.arange(sample.vertex_count), counts)
    divisor = np.where(connected, counts, 1)

    for _ in range(operation.iterations):
        sums = np.bincount(
            owners, weights=values[neighbours], minlength=sample.vertex_count,
        )
        averaged = sums / divisor
        values = np.where(
            connected,
            values * (1.0 - operation.factor) + averaged * operation.factor,
            values,
        )
    return values


@OpRegistry.register_scene(OpType.CONTACT_DIFFUSION)
def _apply_contact_diffusion(operation, fields: FieldSet) -> None:
    """ Blend each receiver vertex toward the nearest source vertex within radius.

    Sources are snapshotted before anything is written, so an object that is
    both a source and a receiver contributes its original temperatures rather
    than its partially-updated ones, and the result does not depend on the
    order objects happen to be visited in.
    """
    source_keys = operation.source.resolve(fields)
    receiver_keys = operation.receiver.resolve(fields)
    if not source_keys or not receiver_keys:
        return

    # Snapshot per source object, so a receiver can exclude itself.
    snapshots = {
        key: (fields.sample_for(key).positions, fields.field_for(key).values.copy())
        for key in source_keys
    }

    for receiver_key in receiver_keys:
        contributors = [
            snapshot for key, snapshot in snapshots.items() if key != receiver_key
        ]
        if not contributors:
            continue

        source_positions = np.concatenate([positions for positions, _ in contributors])
        source_values = np.concatenate([values for _, values in contributors])
        if not source_positions.size:
            continue

        field = fields.field_for(receiver_key)
        fields.set_field(receiver_key, field.with_values(_blend_toward_sources(
            operation,
            fields.sample_for(receiver_key).positions,
            field.values,
            source_positions,
            source_values,
        )))


def _blend_toward_sources(
    operation,
    receiver_positions: np.ndarray,
    receiver_values: np.ndarray,
    source_positions: np.ndarray,
    source_values: np.ndarray,
) -> np.ndarray:
    """ For each receiver vertex, blend toward its nearest source within radius.

    :param block_size: how many receiver vertices are compared against every
        source at once
    """
    result = receiver_values.copy()
    # Actually cap this so that we do not allocate huge vectors for no reason.
    block_size = max(1, 1_000_000 // max(1, source_positions.shape[0] * 3))
    for start in range(0, receiver_positions.shape[0], block_size):
        block = receiver_positions[start:start + block_size]

        # (block, sources) squared distances, avoiding the sqrt until needed.
        deltas = block[:, None, :] - source_positions[None, :, :]
        squared = np.einsum('ijk,ijk->ij', deltas, deltas)

        nearest = np.argmin(squared, axis=1)
        distances = np.sqrt(squared[np.arange(block.shape[0]), nearest])

        # 1 at the source, 0 at the radius, shaped by the falloff curve.
        proximity = np.clip(1.0 - distances / operation.radius, 0.0, 1.0)
        weights = operation.strength * FalloffFunctions.evaluate(proximity, operation.falloff)

        block_values = result[start:start + block_size]
        result[start:start + block_size] = (
            block_values * (1.0 - weights) + source_values[nearest] * weights
        )

    return result
