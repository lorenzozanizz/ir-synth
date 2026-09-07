""" Turns a SceneThermalConfig plus per-object geometry into a FieldSet.

The evaluations proceeds in two stages: evaluate every source into a field, then fold the scene's
operations over the whole set.

The operation stage is injected and not imported, evaluate() is handed an
apply_operation callable. This keeps the pipeline from depending on the registry,
and lets a test drive the fold with a stub.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Mapping, Optional, Tuple

from .baking import BakeStrategyRegistry
from .config import SceneThermalConfig
from .field import FieldSet, MeshSample, ObjectKey, TemperatureField


class FailureReason(Enum):
    """ Why one object, or one operation, did not produce a result. """

    # The spec's parameters are physically invalid, or its evaluator rejected
    # the inputs it was given.
    INVALID_SPEC = auto()
    # No evaluator is registered for this spec or operation type yet.
    NOT_IMPLEMENTED = auto()
    # The config names an object with no matching MeshSample.
    MISSING_GEOMETRY = auto()
    # An operation raised while running.
    OPERATION_FAILED = auto()


@dataclass(frozen=True)
class Failure:
    """ One thing that went wrong, with enough detail to report it.

    :param key: the object involved, or None for a scene-level operation.
    :param operation_index: position in the config's operation list, or None
        when the failure happened during the source stage.
    """

    reason: FailureReason
    detail: str
    key: Optional[ObjectKey] = None
    operation_index: Optional[int] = None


@dataclass(frozen=True)
class PipelineResult:
    """ Everything one evaluation produced.

    :param fields: the objects that succeeded. Objects that failed their
        source stage are absent entirely.
    :param failures: in the order they occurred.
    """

    fields: FieldSet
    failures: Tuple[Failure, ...] = ()

    def succeeded(self) -> bool:
        return not self.failures


# Applies one operation to the whole FieldSet, in place. Supplied by the
# caller
ApplyOperationFn = Callable[[object, FieldSet], None]


class BakingPipeline:

    @staticmethod
    def evaluate(
        config: SceneThermalConfig,
        samples: Mapping[ObjectKey, MeshSample],
        apply_operation: Optional[ApplyOperationFn] = None,
        collections: Optional[Mapping[ObjectKey, Tuple[str, ...]]] = None,
    ) -> PipelineResult:
        """ Evaluate a config against the geometry it applies to.

        :param config: sources and operations
        :param samples: geometry for each object named in config.sources
        :param apply_operation: how to run one operation. Required only when
            config.operations is non-empty
        :param collections: object key -> the collections it belongs to, for
            operations scoped by collection.
        """
        fields, failures = BakingPipeline._evaluate_sources(config, samples, collections or {})
        failures += BakingPipeline._apply_operations(config, fields, apply_operation)
        return PipelineResult(fields=fields, failures=failures)

    @staticmethod
    def _evaluate_sources(
        config: SceneThermalConfig,
        samples: Mapping[ObjectKey, MeshSample],
        collections: Mapping[ObjectKey, Tuple[str, ...]],
    ) -> Tuple[FieldSet, Tuple[Failure, ...]]:
        """ Run every source spec into its object's initial field. """
        fields = FieldSet()
        failures = []

        for key in config.keys():
            mesh_data = samples.get(key)
            if mesh_data is None:
                failures.append(Failure(
                    reason=FailureReason.MISSING_GEOMETRY,
                    detail=f"No MeshSample was supplied for {key!r}",
                    key=key,
                ))
                continue

            spec = config.sources[key]
            try:
                values = BakeStrategyRegistry.evaluate(spec, mesh_data)
            except NotImplementedError as error:
                failures.append(Failure(FailureReason.NOT_IMPLEMENTED, str(error), key=key))
                continue
            except ValueError as error:
                failures.append(Failure(FailureReason.INVALID_SPEC, str(error), key=key))
                continue
            field = TemperatureField.build(values)
            try:
                field.validate()
                fields.add(key, field, mesh_data, collections.get(key, ()))
            except ValueError as error:
                failures.append(Failure(FailureReason.INVALID_SPEC, str(error), key=key))

        return fields, tuple(failures)

    @staticmethod
    def _apply_operations(
        config: SceneThermalConfig,
        fields: FieldSet,
        apply_operation: Optional[ApplyOperationFn],
    ) -> Tuple[Failure, ...]:
        """ Fold the operation list over the assembled FieldSet, in order.

        A failing operation is skipped and the fold continues so that a broken entry in a
        long stack does not discard the work of the others.
        """
        if not config.operations:
            return ()

        if apply_operation is None:
            return (Failure(
                reason=FailureReason.NOT_IMPLEMENTED,
                detail=(
                    f"The config carries {len(config.operations)} operation(s) but no "
                    f"apply_operation was supplied to evaluate()"
                ),
            ),)

        failures = []
        for index, operation in enumerate(config.operations):
            try:
                apply_operation(operation, fields)
            except NotImplementedError as error:
                failures.append(Failure(
                    FailureReason.NOT_IMPLEMENTED, str(error), operation_index=index,
                ))
            except (ValueError, KeyError) as error:
                failures.append(Failure(
                    FailureReason.OPERATION_FAILED, str(error), operation_index=index,
                ))
        return tuple(failures)
