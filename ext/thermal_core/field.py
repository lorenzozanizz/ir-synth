"""
Main classes:

MeshSample        : the geometry of one object, as bpy-agnostic plain numpy arrays.
TemperatureField  : the values over that geometry.
FieldSet          : every object's field + geometry, for the entire scene

The operator layer extracts a MeshSample from a bpy Object once and then
the core works only with arrays. This allows CI/CD testing without launching Blender,
and will later let a randomization hook create bakes headless.

Enough geometric information is required to both create a field form initial specifications
and transform it with scene-wide transformations.

MeshSample.positions is in WORLD space and not object-local space. Object-local
would be cheaper to extract, but any operation that reads two objects at once
needs them in a shared frame, and converting after the fact means every such
operation re-implements the same matrix multiply.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Dict, ItemsView, Iterator, Optional, Tuple

import numpy as np


# type hint
# A stable, hashable identifier for one object inside a FieldSet.
#
# Currently the object's Blender name. Names are unique within a .blend and
# survive being written to a config file, which a bpy pointer does not.
ObjectKey = str


class FieldDomain(Enum):
    """ Which mesh elements a field values are attached to.

    Only POINT exists today, and the baked mesh attribute is written on the
    point domain to match.
    """

    POINT = "Point"


@dataclass(frozen=True, eq=False)
class MeshSample:
    """ One object's geometry, extracted from bpy into plain arrays to become
    bpy-free.

    Frozen because nothing  should edit geometry, and eq=False
    because numpy arrays have no scalar __eq__.

    :param vertex_count: number of vertices, N.
    :param positions: (N, 3) float64, world space. See the module docstring.
    :param edges: (E, 2) int32 of vertex index pairs. Undirected and listed
        once each as adjacency
    :param vertex_group_weights: (N,) float64 in [0, 1], or None when the
        resolved spec does not need weights. Vertices absent from the group
        read as 0.0 ( initialized from np.zero )
    """

    vertex_count: int
    positions: np.ndarray
    edges: np.ndarray
    vertex_group_weights: Optional[np.ndarray] = None

    # Derived, cached on first use. Declared here so the dataclass knows about
    # the slot
    _adjacency: Optional[Tuple[np.ndarray, np.ndarray]] = dataclass_field(
        default=None, init=False, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """ Raise ValueError if the arrays are not mutually consistent. """
        if self.vertex_count < 0:
            raise ValueError(f"MeshSample.vertex_count must be >= 0, got {self.vertex_count}")
        if self.edges.size and (
            self.edges.min() < 0 or self.edges.max() >= self.vertex_count
        ):
            raise ValueError("MeshSample.edges references a vertex index outside "
                f"[0, {self.vertex_count})")

        if self.vertex_group_weights is not None and self.vertex_group_weights.shape != (self.vertex_count,):
            raise ValueError(
                f"MeshSample.vertex_group_weights must have shape "
                f"({self.vertex_count},), got {self.vertex_group_weights.shape}"
            )

    # Static builder, use the default constructor for the dataclass
    @staticmethod
    def build(
        positions: np.ndarray,
        edges: np.ndarray,
        vertex_group_weights: Optional[np.ndarray] = None,
    ) -> "MeshSample":
        """ Construct a MeshSample from loosely-typed arrays.
        Normalizes dtypes and infers vertex_count from positions.
        """
        positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
        edges = np.asarray(edges, dtype=np.int32).reshape(-1, 2)
        if vertex_group_weights is not None:
            vertex_group_weights = np.asarray(vertex_group_weights, dtype=np.float64)
        return MeshSample(
            vertex_count=positions.shape[0],
            positions=positions,
            edges=edges,
            vertex_group_weights=vertex_group_weights,
        )

    def adjacency(self) -> Tuple[np.ndarray, np.ndarray]:
        """ Neighbour lookup in compressed form, computed once and cached.

        Returns (offsets, neighbours) where the neighbours of the i-th vertex are
        neighbours[offsets[i]:offsets[i + 1]]. offsets has length N + 1.

        numpy slicing into a contiguous array is far cheaper than walking
        Python lists. Each edge contributes in both directions, so an edge
        (a, b) puts b among a's neighbours and a among b's.
        """
        if self._adjacency is not None:
            return self._adjacency

        # Both directions of every undirected edge.
        if self.edges.size:
            sources = np.concatenate([self.edges[:, 0], self.edges[:, 1]])
            targets = np.concatenate([self.edges[:, 1], self.edges[:, 0]])
        else:
            sources = np.empty(0, dtype=np.int64)
            targets = np.empty(0, dtype=np.int64)

        # Group targets by source: sort by source, then a running count of how
        # many entries each source owns gives the offsets.
        order = np.argsort(sources, kind="stable")
        neighbours = targets[order].astype(np.int32, copy=False)
        counts = np.bincount(sources, minlength=self.vertex_count)
        offsets = np.zeros(self.vertex_count + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])

        result = (offsets, neighbours)
        # Frozen dataclass, so the cache has to be written the long way round.
        object.__setattr__(self, "_adjacency", result)
        return result

    def has_geometry(self) -> bool:
        """ Whether this sample carries anything an operation could act on. Trivial check
        """
        return self.vertex_count > 0 and self.edges.size > 0


@dataclass(frozen=True, eq=False)
class TemperatureField:
    """ Kelvin values over one object's mesh elements.

    Immutable by convention as well as by dataclass: operations return a new
    field.
    The pipeline owns storage and decides what gets kept, which is what makes
    a muted or failed operation a clean no-op instead of a partial edit.

    :param values: (N,) float64 Kelvin, aligned to the elements of the given domain
    :param domain: which mesh elements the values sit on.
    """

    values: np.ndarray
    domain: FieldDomain = FieldDomain.POINT

    @staticmethod
    def build(values: np.ndarray, domain: FieldDomain = FieldDomain.POINT) -> "TemperatureField":
        """ Construct a field, coercing values to a flat float64 array. """
        return TemperatureField(
            values=np.asarray(values, dtype=np.float64).reshape(-1),
            domain=domain,
        )

    @staticmethod
    def uniform(
        value_k: float, count: int, domain: FieldDomain = FieldDomain.POINT
    ) -> "TemperatureField":
        """ A field of one repeated value. """
        return TemperatureField(
            values=np.full(int(count), float(value_k), dtype=np.float64), domain=domain,
        )

    def __len__(self) -> int:
        return int(self.values.shape[0])

    def with_values(self, values: np.ndarray) -> "TemperatureField":
        """ A new field of the same domain and length carrying ``values``.

        The length check is the guard rail for the operation registry: an
        operation that returns the wrong number of values is caught at the
        point of return, naming itself, rather than surfacing later as a
        confusing foreach_set failure inside Blender.
        """
        values = np.asarray(values, dtype=np.float64).reshape(-1)
        if values.shape[0] != len(self):
            raise ValueError(
                f"TemperatureField.with_values expected {len(self)} values, "
                f"got {values.shape[0]}"
            )
        return TemperatureField(values=values, domain=self.domain)

    def validate(self) -> None:
        """ Raise ValueError if the field holds values that cannot be a
        temperature: non-finite, or below absolute zero.
        """
        if not np.all(np.isfinite(self.values)):
            raise ValueError("TemperatureField contains NaN or infinite values")
        if self.values.size and float(self.values.min()) < 0.0:
            raise ValueError(
                f"TemperatureField contains a value below absolute zero "
                f"({float(self.values.min())}K)"
            )

    def range_k(self) -> Tuple[float, float]:
        """ (min, max) in Kelvin, or (0.0, 0.0) for an empty field. """
        if not self.values.size:
            return 0.0, 0.0
        return float(self.values.min()), float(self.values.max())

    def mean_k(self) -> float:
        """ Mean Kelvin, or 0.0 for an empty field. """
        return float(self.values.mean()) if self.values.size else 0.0


class FieldSet:
    """ Every object's field and geometry for one bake, keyed by ObjectKey which
    is an hashable key.

    Deliberately mutable, a scene-level operation may
    rewrite several objects, and both need to see the geometry alongside the values.

    Geometry is fixed for the lifetime of a FieldSet. Re-baking is necessary if
    geometry has to change.
    """

    def __init__(self) -> None:
        self._fields: Dict[ObjectKey, TemperatureField] = {}
        self._samples: Dict[ObjectKey, MeshSample] = {}
        self._collections: Dict[ObjectKey, Tuple[str, ...]] = {}

    def add(
        self,
        key: ObjectKey,
        field: TemperatureField,
        sample: MeshSample,
        collections: Tuple[str, ...] = (),
    ) -> None:
        """ Register an object's initial field and its geometry.

        :raises ValueError: field length disagrees with the sample's vertex
            count, or the key is already present.
        """
        if key in self._fields:
            raise ValueError(f"FieldSet already contains an entry for {key!r}")
        if len(field) != sample.vertex_count:
            raise ValueError(
                f"Field for {key!r} has {len(field)} values but its MeshSample "
                f"has {sample.vertex_count} vertices"
            )
        self._fields[key] = field
        self._samples[key] = sample
        self._collections[key] = tuple(collections)

    def set_field(self, key: ObjectKey, field: TemperatureField) -> None:
        """ Replace an existing object's field, keeping its geometry.

        :raises KeyError: no entry for key
        :raises ValueError: the new field's length disagrees with the geometry.
        """
        if key not in self._fields:
            raise KeyError(f"FieldSet has no entry for {key!r}")
        if len(field) != self._samples[key].vertex_count:
            raise ValueError(
                f"Replacement field for {key!r} has {len(field)} values but its "
                f"MeshSample has {self._samples[key].vertex_count} vertices"
            )
        self._fields[key] = field

    def field_for(self, key: ObjectKey) -> TemperatureField:
        """ :raises KeyError: no entry for key """
        return self._fields[key]

    def sample_for(self, key: ObjectKey) -> MeshSample:
        """ :raises KeyError: no entry for key. """
        return self._samples[key]

    def collections_for(self, key: ObjectKey) -> Tuple[str, ...]:
        """ Names of the collections an object belongs to.

        Returns an empty tuple for an unknown key, so an operation scoped to a
        collection simply does not select a deleted object rather than raising.
        """
        return self._collections.get(key, ())

    def keys(self) -> Tuple[ObjectKey, ...]:
        """ Every key, in insertion order.

        Order is stable so that a bake is reproducible.
        """
        return tuple(self._fields.keys())

    def items(self) -> ItemsView[ObjectKey, TemperatureField]:
        return self._fields.items()

    def __contains__(self, key: object) -> bool:
        return key in self._fields

    def __len__(self) -> int:
        return len(self._fields)

    def __iter__(self) -> Iterator[ObjectKey]:
        return iter(self._fields)
