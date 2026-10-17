"""
A bpy independent description and evaluation of a scene's emissivity maps.
Parallel to config.py + pipeline.py for temperature.

The emissivity map does not use TemperatureField or FieldSet, since
we do not need to perform operations like diffusion on emissivity.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

import numpy as np

from .baking import BakeStrategyRegistry
from .config import ConfigError, check_schema_version, _tagged
from .field import MeshSample, ObjectKey
from .pipeline import Failure, FailureReason
from .specs import EmissivitySpec

from ..constants import SCHEMA_VERSION, SCHEMA_VERSION_KEY


@dataclass(frozen=True)
class SceneEmissivityConfig:
    """ Every object's resolved emissivity spec.
    :param sources: object key -> the resolved spec that creates its map.
        An object absent from this mapping gets no emissivity map.
    """

    sources: Mapping[ObjectKey, EmissivitySpec] = field(default_factory=dict)
    def keys(self) -> Tuple[ObjectKey, ...]:
        """ Object keys in a stable order, so bakes are reproducible. """
        return tuple(self.sources.keys())

    def validate(self) -> None:
        """ Validate every spec.
        :raises ConfigError: any spec fails its own validate().
        """
        for key, spec in self.sources.items():
            try:
                spec.validate()
            except ValueError as error:
                raise ConfigError(f"Emissivity spec for {key!r} is invalid: {error}") from error

    def to_dict(self) -> Dict[str, Any]:
        """ Convert to plain JSON (dictionary) data """
        return {
            SCHEMA_VERSION_KEY: SCHEMA_VERSION,
            "sources": {key: _tagged(spec) for key, spec in self.sources.items()},
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "SceneEmissivityConfig":
        """ Rebuild a config produced by to_dict.

        :raises SchemaVersionError: incompatible layout version.
        :raises ConfigError: the data is malformed or names an unknown spec.
        """
        check_schema_version(data)
        raw_sources = data.get("sources", {})
        if not isinstance(raw_sources, Mapping):
            raise ConfigError("'sources' must be a mapping of object key to spec")

        sources: Dict[ObjectKey, EmissivitySpec] = {}
        for key, entry in raw_sources.items():
            try:
                spec_class = EmissivitySpec.named(entry["type"])
                sources[key] = spec_class.from_params(entry.get("params", {}))
            except (KeyError, TypeError) as error:
                raise ConfigError(f"Could not rebuild the emissivity spec for {key!r}: {error}") from error
        return SceneEmissivityConfig(sources=sources)


def validate_emissivity_values(values: np.ndarray) -> None:
    """ Raise ValueError if values cannot be emissivity: non-finite, or
    outside [0, 1].
    """
    if not np.all(np.isfinite(values)):
        raise ValueError("Emissivity map contains NaN or infinite values")
    if values.size and (float(values.min()) < 0.0 or float(values.max()) > 1.0):
        raise ValueError(
            f"Emissivity map has values outside [0, 1] "
            f"({float(values.min())}, {float(values.max())})"
        )


class EmissivityPipeline:
    """ Turns a SceneEmissivityConfig plus geometry into per-vertex maps. """

    @staticmethod
    def evaluate(
        config: SceneEmissivityConfig,
        samples: Mapping[ObjectKey, MeshSample],
    ) -> Tuple[Dict[ObjectKey, np.ndarray], Tuple[Failure, ...]]:
        """ Evaluate every spec into its object's emissivity map. A failing object is recorded and s
        kipped while the others continue.

        :param config: the resolved emissivity specs.
        :param samples: geometry for each object named in config.sources.
        :return: (object key -> (N,) float64 emissivity, failures in order)
        """
        maps: Dict[ObjectKey, np.ndarray] = {}
        failures = []

        for key in config.keys():
            sample = samples.get(key)
            if sample is None:
                failures.append(Failure(
                    FailureReason.MISSING_GEOMETRY,
                    f"No MeshSample was supplied for {key!r}",
                    key=key,
                ))
                continue

            try:
                values = BakeStrategyRegistry.evaluate(config.sources[key], sample)
                validate_emissivity_values(values)
            except NotImplementedError as error:
                failures.append(Failure(FailureReason.NOT_IMPLEMENTED, str(error), key=key))
                continue
            except ValueError as error:
                failures.append(Failure(FailureReason.INVALID_SPEC, str(error), key=key))
                continue
            maps[key] = values

        return maps, tuple(failures)
