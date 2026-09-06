"""
The complete, bpy-free description of how a scene's temperature field is
produced: one source spec per object, plus a scene-wide ordered list of
operations applied afterwards.

This is the only input `pipeline.evaluate` needs. The UI builds one from bpy
state; a randomization hook builds or mutates one directly.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Tuple

from .field import ObjectKey
# This time its a concrete implementation and not just a stub
from .operations import FieldOperation
from .specs import TempInitSpec



class ConfigError(Exception):
    """ Raised when a SceneThermalConfig is structurally invalid. Depends on the config type.  """




@dataclass(frozen=True)
class SceneThermalConfig:
    """ Every object's source strategy, and the operations run over the result

    :param sources: object key -> the resolved spec that creates its field. In this way an object
        absent from this mapping is not baked at all.
    :param operations: applied in order after every source has been evaluated
    """

    sources: Mapping[ObjectKey, TempInitSpec] = field(default_factory=dict)
    operations: Tuple[FieldOperation, ...] = ()

    def keys(self) -> Tuple[ObjectKey, ...]:
        """ Object keys in a stable order, so bakes are reproducible. """
        return tuple(self.sources.keys())

    def validate(self) -> None:
        """ Validate every source spec and every operation.

        :raises ConfigError: any member fails its own validate().
        """
        # Note that this exceptions are not propagated to Blender, they are intercepted
        # by the UI layer and presented.
        for key, spec in self.sources.items():
            try:
                spec.validate()
            except ValueError as error:
                raise ConfigError(f"Source spec for {key!r} is invalid: {error}") from error

        for index, operation in enumerate(self.operations):
            validate = getattr(operation, "validate", None)
            if validate is None:
                continue
            try:
                validate()
            except ValueError as error:
                raise ConfigError(f"Operation {index} is invalid: {error}") from error

    def with_sources(self, sources: Mapping[ObjectKey, TempInitSpec]) -> "SceneThermalConfig":
        """ A copy carrying different sources and the same operations. """
        return SceneThermalConfig(sources=dict(sources), operations=self.operations)

    def with_operations(self, operations: Tuple[FieldOperation, ...]) -> "SceneThermalConfig":
        """ A copy carrying different operations and the same sources. """
        return SceneThermalConfig(sources=dict(self.sources), operations=tuple(operations))

    def to_dict(self) -> Dict[str, Any]:
        """ Convert to plain JSON (dictionary) data.

        Each entry records its class name alongside its fields, which is what
        from_dict uses to pick the class to rebuild when its needed.
        """
        # Simply enumerate all operatiosn and initializations.
        return {
            "sources": {
                key: _tagged(spec) for key, spec in self.sources.items()
            },
            "operations": [_tagged(operation) for operation in self.operations],
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "SceneThermalConfig":
        """ Rebuild a config produced by to_dict.

        Operations are not rebuilt yet; the operation registry arrives in
        phase 3 and will supply the class lookup.

        :raises ConfigError: the data is malformed or names an unknown spec.
        """
        raw_sources = data.get("sources", {})
        if not isinstance(raw_sources, Mapping):
            raise ConfigError("'sources' must be a mapping of object key to spec")

        sources: Dict[ObjectKey, TempInitSpec] = {}
        for key, entry in raw_sources.items():
            try:
                spec_class = TempInitSpec.named(entry["type"])
                # Construct the required type. This allows to serialize
                # and deserialize scene configs.
                sources[key] = spec_class(**entry.get("params", {}))
            except (KeyError, TypeError) as error:
                raise ConfigError(
                    f"Could not rebuild the source spec for {key!r}: {error}"
                ) from error

        operations = []
        for index, entry in enumerate(data.get("operations", ())):
            try:
                op_class = FieldOperation.named(entry["type"])
                operations.append(op_class.from_params(entry.get("params", {})))
            except (KeyError, TypeError) as error:
                raise ConfigError(
                    f"Could not rebuild operation {index}: {error}"
                ) from error

        return SceneThermalConfig(sources=sources, operations=tuple(operations))


def _tagged(item: Any) -> Dict[str, Any]:
    """ A dataclass as {"type": class name, "params": its fields}. """
    if not is_dataclass(item):
        raise ConfigError(f"{type(item).__name__} is not a dataclass and cannot be serialized")
    return {"type": type(item).__name__, "params": asdict(item, dict_factory=_json_safe)}


# bug fix: previous version serialized incorrectly.
def _json_safe(pairs) -> Dict[str, Any]:
    """ asdict dict_factory that converts Enum members to their names.
    """
    return {
        key: (value.name if isinstance(value, Enum) else value)
        for key, value in pairs
    }
