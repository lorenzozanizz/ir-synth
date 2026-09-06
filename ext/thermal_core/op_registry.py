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
