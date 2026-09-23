""" Tests for the hook registry.

Everything here uses plain strings, lists and dictionaries as payloads. The
registry is generic on purpose, so these tests need no config, no field and no
Blender. If a test here ever needs thermal_core, the registry has grown a
dependency it should not have.
"""

import pytest

from ext.hooks.registry import (
    DispatchResult,
    HookContext,
    HookEntry,
    HookError,
    HookFailureReason,
    HookPoint,
    HookRegistry,
)


@pytest.fixture
def registry() -> HookRegistry:
    """ A fresh registry per test, so no test can leak into another. """
    return HookRegistry()


def test_decorator_registers_and_returns_the_function_unchanged(registry):
    """ The function must stay directly callable, so it stays testable. """

    @registry.register(HookPoint.CONFIG_BUILT)
    def make_it_hot(payload, context):
        return payload + "!"

    assert make_it_hot("x", HookContext()) == "x!"
    assert registry.names_for(HookPoint.CONFIG_BUILT) == ("make_it_hot",)


def test_add_registers_without_the_decorator(registry):
    entry = registry.add(HookPoint.FIELDS_EVALUATED, lambda p, c: None, name="solver")

    assert isinstance(entry, HookEntry)
    assert entry.point is HookPoint.FIELDS_EVALUATED
    assert entry.priority == 0
    assert "solver" in registry


def test_the_default_name_is_the_function_name(registry):
    def external_solver(payload, context):
        return None

    registry.add(HookPoint.FIELDS_EVALUATED, external_solver)

    assert registry.names_for(HookPoint.FIELDS_EVALUATED) == ("external_solver",)


def test_a_duplicate_name_is_refused(registry):
    """ Re-running a Blender script must not register the same hook twice. """
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="randomize")

    with pytest.raises(HookError):
        registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="randomize")


def test_a_duplicate_name_can_be_replaced_on_purpose(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: "first", name="randomize")
    registry.add(
        HookPoint.CONFIG_BUILT, lambda p, c: "second", name="randomize",
        replace_existing=True,
    )

    assert registry.names_for(HookPoint.CONFIG_BUILT) == ("randomize",)
    assert registry.dispatch(HookPoint.CONFIG_BUILT, "x").value == "second"


def test_the_same_name_may_be_used_at_two_different_points(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="log")
    registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="log")

    assert len(registry) == 2


def test_a_non_callable_is_refused(registry):
    with pytest.raises(HookError):
        registry.add(HookPoint.CONFIG_BUILT, "not a function")


def test_a_bad_point_is_refused(registry):
    with pytest.raises(HookError):
        registry.add("CONFIG_BUILT", lambda p, c: None)


def test_remove_and_clear(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="a")
    registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="a")
    registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="b")

    assert registry.remove("a", point=HookPoint.CONFIG_BUILT) == 1
    assert registry.remove("a") == 1
    assert registry.names_for(HookPoint.BAKE_FINISHED) == ("b",)

    registry.clear()
    assert len(registry) == 0

def test_hooks_run_in_priority_order(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="late", priority=10)
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="early", priority=-5)
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="middle")

    assert registry.names_for(HookPoint.CONFIG_BUILT) == ("early", "middle", "late")


def test_equal_priority_keeps_registration_order(registry):
    """ Reproducibility: the order must never depend on dict iteration. """
    for name in ("first", "second", "third", "fourth"):
        registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name=name)

    assert registry.names_for(HookPoint.CONFIG_BUILT) == (
        "first", "second", "third", "fourth",
    )


def test_ordering_survives_a_removal_and_a_re_add(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="a")
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="b")
    registry.remove("a")
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="a")

    # 'a' was registered again later, so it now runs after 'b'.
    assert registry.names_for(HookPoint.CONFIG_BUILT) == ("b", "a")


# -- dispatch ------------------------------------------------------------


def test_dispatch_with_no_hooks_returns_the_payload_unchanged(registry):
    result = registry.dispatch(HookPoint.CONFIG_BUILT, "payload")

    assert isinstance(result, DispatchResult)
    assert result.value == "payload"
    assert result.ok


def test_returning_none_means_no_change(registry):
    seen = []

    registry.add(
        HookPoint.CONFIG_BUILT,
        lambda p, c: seen.append(p),   # append returns None
        name="observer",
    )

    assert registry.dispatch(HookPoint.CONFIG_BUILT, "payload").value == "payload"
    assert seen == ["payload"]


def test_hooks_chain_each_receiving_the_previous_result(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|a", name="a", priority=1)
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|b", name="b", priority=2)

    assert registry.dispatch(HookPoint.CONFIG_BUILT, "base").value == "base|a|b"


def test_an_observer_between_two_editors_does_not_break_the_chain(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|a", name="a", priority=1)
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: None, name="look", priority=2)
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|c", name="c", priority=3)

    assert registry.dispatch(HookPoint.CONFIG_BUILT, "base").value == "base|a|c"


def test_hooks_at_another_point_do_not_run(registry):
    registry.add(HookPoint.BAKE_FINISHED, lambda p, c: "wrong", name="other")

    assert registry.dispatch(HookPoint.CONFIG_BUILT, "right").value == "right"


def test_the_context_reaches_the_hook(registry):
    received = {}

    def capture(payload, context):
        received["context"] = context
        return None

    registry.add(HookPoint.CONFIG_BUILT, capture)
    context = HookContext(scene_name="Scene", frame=7, seed=42)
    registry.dispatch(HookPoint.CONFIG_BUILT, "x", context=context)

    assert received["context"] is context


def test_a_default_context_is_supplied_when_none_is_given(registry):
    received = {}

    def capture(payload, context):
        received["context"] = context
        return None

    registry.add(HookPoint.CONFIG_BUILT, capture)
    registry.dispatch(HookPoint.CONFIG_BUILT, "x")

    assert isinstance(received["context"], HookContext)


# -- failure handling ----------------------------------------------------


def test_a_raising_hook_stops_the_run_in_strict_mode(registry):
    def boom(payload, context):
        raise ValueError("the solver did not converge")

    registry.add(HookPoint.FIELDS_EVALUATED, boom, name="solver")

    with pytest.raises(HookError) as info:
        registry.dispatch(HookPoint.FIELDS_EVALUATED, "fields")

    assert "solver" in str(info.value)
    assert isinstance(info.value.__cause__, ValueError)


def test_a_raising_hook_is_recorded_in_tolerant_mode(registry):
    registry.add(
        HookPoint.FIELDS_EVALUATED,
        lambda p, c: (_ for _ in ()).throw(ValueError("nope")),
        name="solver",
    )

    result = registry.dispatch(HookPoint.FIELDS_EVALUATED, "fields", strict=False)

    assert result.value == "fields"
    assert not result.ok
    assert result.failures[0].name == "solver"
    assert result.failures[0].reason is HookFailureReason.HOOK_RAISED
    assert isinstance(result.failures[0].error, ValueError)


def test_a_wrong_return_type_is_refused_in_strict_mode(registry):
    """ Catches the common mistake early, near its cause. """
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: {"sources": {}}, name="bad")

    with pytest.raises(HookError):
        registry.dispatch(HookPoint.CONFIG_BUILT, "a config")


def test_a_wrong_return_type_is_recorded_in_tolerant_mode(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: 123, name="bad")

    result = registry.dispatch(HookPoint.CONFIG_BUILT, "a config", strict=False)

    assert result.value == "a config"
    assert result.failures[0].reason is HookFailureReason.WRONG_RETURN_TYPE


def test_tolerant_mode_keeps_running_the_remaining_hooks(registry):
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|a", name="a", priority=1)
    registry.add(
        HookPoint.CONFIG_BUILT,
        lambda p, c: (_ for _ in ()).throw(RuntimeError("x")),
        name="broken", priority=2,
    )
    registry.add(HookPoint.CONFIG_BUILT, lambda p, c: p + "|c", name="c", priority=3)

    result = registry.dispatch(HookPoint.CONFIG_BUILT, "base", strict=False)

    assert result.value == "base|a|c"
    assert len(result.failures) == 1


def test_the_registry_default_strictness_applies(registry):
    tolerant = HookRegistry(strict=False)
    tolerant.add(HookPoint.CONFIG_BUILT, lambda p, c: 1, name="bad")

    assert not tolerant.dispatch(HookPoint.CONFIG_BUILT, "text").ok


def test_strict_is_the_default(registry):
    assert registry.strict is True


def test_a_subclass_return_is_accepted(registry):
    """ The check is isinstance, not an exact type match. """

    class Special(dict):
        pass

    registry.add(HookPoint.SAMPLES_BUILT, lambda p, c: Special(a=1), name="swap")
    result = registry.dispatch(HookPoint.SAMPLES_BUILT, {})

    assert isinstance(result.value, Special)


def test_scoped_restores_the_previous_hooks(registry):
    registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="permanent")

    with registry.scoped():
        registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="temporary")
        assert registry.names_for(HookPoint.BAKE_FINISHED) == (
            "permanent", "temporary",
        )

    assert registry.names_for(HookPoint.BAKE_FINISHED) == ("permanent",)


def test_scoped_restores_even_when_the_body_raises(registry):
    with pytest.raises(RuntimeError):
        with registry.scoped():
            registry.add(HookPoint.BAKE_FINISHED, lambda p, c: None, name="temporary")
            raise RuntimeError("the bake failed")

    assert len(registry) == 0


def test_scoped_restores_the_strict_flag(registry):
    with registry.scoped():
        registry.strict = False

    assert registry.strict is True


# -- context -------------------------------------------------------------


def test_context_metadata_is_read_only():
    """ One hook must not be able to edit what later hooks will see. """
    context = HookContext(metadata={"index": 3})

    with pytest.raises(TypeError):
        context.metadata["index"] = 9


def test_with_metadata_does_not_touch_the_original():
    context = HookContext(metadata={"index": 3})

    extended = context.with_metadata(batch=1)

    assert dict(extended.metadata) == {"index": 3, "batch": 1}
    assert dict(context.metadata) == {"index": 3}


def test_the_same_seed_gives_the_same_numbers():
    """ The reproducibility guarantee, stated as a test. """
    first = HookContext(seed=42).rng(0).random(5)
    second = HookContext(seed=42).rng(0).random(5)

    assert (first == second).all()


def test_different_streams_give_different_numbers():
    context = HookContext(seed=42)

    assert (context.rng(0).random(5) != context.rng(1).random(5)).any()


def test_asking_for_a_generator_without_a_seed_is_an_error():
    with pytest.raises(HookError):
        HookContext().rng()


def test_the_context_carries_no_blender_object_by_default():
    context = HookContext(scene_name="Scene")

    assert context.scene is None
