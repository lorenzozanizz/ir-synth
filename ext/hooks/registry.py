""" The hook registry which controls how external code takes part in a bake.
A h oook receives the object produced by a stage of the bake, plus a
HookContext describing the run. It returns a replacement, or it
returns None.

Hooks run by ascending priority, and hooks of equal
priority run in registration order.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from itertools import count
from types import MappingProxyType
from typing import (
    Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple,
)


class HookPoint(Enum):
    """ Where in a bake a hook runs.
    """

    # Payload: SceneThermalConfig, straight after it was built from the scene
    # or supplied by the caller. The main point: randomization lives here.
    CONFIG_BUILT = auto()

    # Payload: Dict[ObjectKey, MeshSample], after geometry was sampled.
    SAMPLES_BUILT = auto()

    # Payload: FieldSet, after evaluation and before anything is written.
    # The second main point: an external solver replaces the values here.
    FIELDS_EVALUATED = auto()

    # Payload: Dict[ObjectKey, BakeOutcome], after writing. Observation and
    # side outputs, such as a label file for the sample just produced.
    BAKE_FINISHED = auto()


class HookError(Exception):
    """ Raised when a hook misbehaves, or when the registry is misused.
    """


class HookFailureReason(Enum):
    """ Why one hook did not contribute.
    """

    # The hook raised while running.
    HOOK_RAISED = auto()
    # The hook returned an object of the wrong type.
    WRONG_RETURN_TYPE = auto()


@dataclass(frozen=True)
class HookFailure:
    """ One hook that did not contribute, with enough detail to report it.

    :param name: the registered name of the hook.
    :param point: where it was running.
    :param reason: what kind of problem it was.
    :param detail: a message for a human.
    :param error: the original exception, when there was one.
    """

    name: str
    point: HookPoint
    reason: HookFailureReason
    detail: str
    error: Optional[BaseException] = None


@dataclass(frozen=True)
class DispatchResult:
    """ Everything one dispatch produced.

    :param value: the payload after every contributing hook ran. Equal to the
        payload that went in when no hook replaced it.
    :param failures: empty in strict mode, because strict mode raises instead.
    """

    value: Any
    failures: Tuple[HookFailure, ...] = ()

    @property
    def ok(self) -> bool:
        """ Whether every hook contributed without a problem. """
        return not self.failures


@dataclass(frozen=True)
class HookContext:
    """ What a hook is told about the run it is taking part in. immutable.

    :param scene_name: the name of the scene being baked, or None outside
        (a string)
    :param frame: the frame being baked, when there is one.
    :param seed: the seed a randomizing hook should derive frame.
    :param metadata: anything the caller wants to pass down, such as the index
        of the sample in a dataset. Read-only.
    :param scene: the live bpy scene, when the bake is running inside Blender otherwise None.
    """

    scene_name: Optional[str] = None
    frame: Optional[int] = None
    seed: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    scene: Any = None

    def __post_init__(self) -> None:
        # Wrapped so a hook cannot edit what later hooks will see.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def with_metadata(self, **entries: Any) -> "HookContext":
        """ A copy with extra metadata. The original is unchanged.
        :param entries: keys to add or overwrite.
        """
        merged = dict(self.metadata)
        merged.update(entries)
        return replace(self, metadata=merged)

    def rng(self, stream: int = 0):
        """ A NumPy random generator seeded from this context.

        :param stream: distinguishes independent streams under the same seed.
            Give each hook its own constant.
        :raises HookError: the context carries no seed.
        """
        # Imported here so that this module stays importable with no NumPy
        # ( the idea is to let this be ok with very small applications without numpy in their
        # interpreter, even if blender has it internally )
        import numpy as np

        if self.seed is None:
            raise HookError(
                "This HookContext carries no seed, so a reproducible random "
                "generator cannot be made. Pass seed= when building it."
            )
        return np.random.default_rng([self.seed, stream])


# A hook takes the payload and the context, and returns a replacement or None.
HookFunction = Callable[[Any, HookContext], Optional[Any]]


@dataclass(frozen=True)
class HookEntry:
    """ One registered hook.

    :param sequence: registration order, used to break priority ties so that
        the running order never depends on dictionary or set iteration.
    """

    point: HookPoint
    name: str
    function: HookFunction
    # By default, priority is zero
    priority: int = 0
    sequence: int = 0

    @property
    def sort_key(self) -> Tuple[int, int]:
        return self.priority, self.sequence


class HookRegistry:
    """ Holds the hooks and runs them.

    :param strict: the default mode for dispatch(). True means a misbehaving hook
        stops the bake and causes an expcetion.
    """

    def __init__(self, strict: bool = True) -> None:
        self._entries: Dict[HookPoint, List[HookEntry]] = {
            point: [] for point in HookPoint
        }
        self._sequence = count()
        self.strict = strict

    def add(
        self,
        point: HookPoint,
        function: HookFunction,
        name: Optional[str] = None,
        priority: int = 0,
        replace_existing: bool = False,
    ) -> HookEntry:
        """ Register a function, without the decorator syntax.

        :param point: when it runs.
        :param function: the hook itself.
        :param name: how it is identified in errors and in remove().
        :param priority: smaller runs earlier.
        :param replace_existing: allow a second registration under a name already in
        use at this point. Off by default
        """
        if not isinstance(point, HookPoint):
            raise HookError(f"{point!r} is not a HookPoint")
        if not callable(function):
            raise HookError(f"The hook registered at {point.name} is not callable")

        resolved = name or getattr(function, "__name__", None) or repr(function)
        existing = [entry for entry in self._entries[point] if entry.name == resolved]
        if existing and not replace_existing:
            raise HookError(
                f"A hook named {resolved!r} is already registered at "
                f"{point.name}. Pass replace_existing=True to overwrite it, or "
                f"give this one a different name."
            )
        if existing:
            self.remove(resolved, point=point)

        entry = HookEntry(
            point=point,
            name=resolved,
            function=function,
            priority=priority,
            sequence=next(self._sequence),
        )
        self._entries[point].append(entry)
        return entry

    def register(
        self,
        point: HookPoint,
        name: Optional[str] = None,
        priority: int = 0,
        replace_existing: bool = False,
    ) -> Callable[[HookFunction], HookFunction]:
        """ Decorator form of add(). See that function for the docstrings """

        def decorator(function: HookFunction) -> HookFunction:
            self.add(
                point,
                function,
                name=name,
                priority=priority,
                replace_existing=replace_existing,
            )
            return function

        return decorator

    def remove(self, name: str, point: Optional[HookPoint] = None) -> int:
        """ Remove every hook with this name.

        :param point: only at this point, or at every point when None.
        :return: how many were removed.
        """
        points = [point] if point is not None else list(HookPoint)
        removed = 0
        for one in points:
            kept = [entry for entry in self._entries[one] if entry.name != name]
            removed += len(self._entries[one]) - len(kept)
            self._entries[one] = kept
        return removed

    def clear(self, point: Optional[HookPoint] = None) -> None:
        """ Remove every hook, at one point or at all of them. """
        points = [point] if point is not None else list(HookPoint)
        for one in points:
            self._entries[one] = []

    def hooks_for(self, point: HookPoint) -> Tuple[HookEntry, ...]:
        """ The hooks at one point, in the order they will run. """
        return tuple(sorted(self._entries[point], key=lambda e: e.sort_key))

    def names_for(self, point: HookPoint) -> Tuple[str, ...]:
        """ The names at one point, in running order. Convenient in tests. """
        return tuple(entry.name for entry in self.hooks_for(point))

    def __len__(self) -> int:
        return sum(len(entries) for entries in self._entries.values())

    def __contains__(self, name: object) -> bool:
        return any(
            entry.name == name
            for entries in self._entries.values()
            for entry in entries
        )

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{point.name}={len(self._entries[point])}" for point in HookPoint
        )
        return f"HookRegistry({counts}, strict={self.strict})"

    @contextmanager
    def scoped(self) -> Iterator["HookRegistry"]:
        """ Register hooks temporarily and restore the previous set on exit.
        """
        snapshot = {point: list(entries) for point, entries in self._entries.items()}
        previous_strict = self.strict
        try:
            yield self
        finally:
            self._entries = snapshot
            self.strict = previous_strict

    def dispatch(
        self,
        point: HookPoint,
        payload: Any,
        context: Optional[HookContext] = None,
        strict: Optional[bool] = None,
    ) -> DispatchResult:
        """ Run every hook at one point, feeding each the previous result.

        A hook returning None leaves does not change any dataclass. A hook returning an
        object replaces it, and the next hook receives the replacement, so a
        chain of hooks composes in priority order.

        The replacement must be an instance of the type that came in.

        :param point: which hooks to run.
        :param payload: the object the stage produced.
        :param context: the description of the run.
        :param strict: overrides the registry default for this call.
        :return: the final payload and the failures, if any.
        """
        is_strict = self.strict if strict is None else strict
        run_context = context if context is not None else HookContext()

        current = payload
        failures: List[HookFailure] = []

        for entry in self.hooks_for(point):
            try:
                returned = entry.function(current, run_context)
            except Exception as error:
                failure = HookFailure(
                    name=entry.name,
                    point=point,
                    reason=HookFailureReason.HOOK_RAISED,
                    detail=f"{type(error).__name__}: {error}",
                    error=error,
                )
                if is_strict:
                    raise HookError(
                        f"The hook {entry.name!r} at {point.name} raised: "
                        f"{type(error).__name__}: {error}"
                    ) from error
                failures.append(failure)
                continue

            if returned is None:
                # "No change" is a return of None, never a separate hook kind.
                continue

            if not isinstance(returned, type(current)):
                detail = (
                    f"returned {type(returned).__name__}, but "
                    f"{type(current).__name__} was expected"
                )
                if is_strict:
                    raise HookError(
                        f"The hook {entry.name!r} at {point.name} {detail}."
                    )
                failures.append(
                    HookFailure(
                        name=entry.name,
                        point=point,
                        reason=HookFailureReason.WRONG_RETURN_TYPE,
                        detail=detail,
                    )
                )
                continue

            current = returned

        return DispatchResult(value=current, failures=tuple(failures))
