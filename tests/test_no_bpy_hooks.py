""" Proves the pure core is importable and usable with no Blender present.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# The directory containing the 'ext' package.
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]


def _run_without_bpy(body: str) -> subprocess.CompletedProcess:
    """ Run body in a subprocess that has no bpy and no bpy stub.

    :param body: Python source to execute.
    """
    source = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(_PACKAGE_PARENT)!r})
        assert "bpy" not in sys.modules
        {textwrap.indent(textwrap.dedent(body), "        ").strip()}
        """
    )
    return subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True,
    )


def _assert_ok(result: subprocess.CompletedProcess) -> None:
    if result.returncode != 0:
        pytest.fail(f"subprocess failed:\n{result.stdout}\n{result.stderr}")


def test_package_import_does_not_pull_in_bpy():
    result = _run_without_bpy(
        """
        import ext
        assert "bpy" not in sys.modules, "importing ext pulled bpy in"
        print("OK")
        """
    )
    _assert_ok(result)


def test_thermal_core_imports_without_blender():
    result = _run_without_bpy(
        """
        from ext.thermal_core.config import SceneThermalConfig
        from ext.thermal_core.specs import UniformTempSpec
        from ext.thermal_core.operations import ClampOp, ContactDiffusionOp, SmoothOp
        from ext.thermal_core.pipeline import BakingPipeline
        from ext.thermal_core.op_registry import OpRegistry
        from ext.thermal_core.radiometry import RBFOTransferSpec, TransferRegistry
        from ext.thermal_core.field import FieldSet, MeshSample, TemperatureField
        assert "bpy" not in sys.modules
        print("OK")
        """
    )
    _assert_ok(result)


def test_full_evaluation_runs_without_blender():
    """ A source spec plus an operation, evaluated end to end, no bpy. """
    result = _run_without_bpy(
        """
        import numpy as np
        from ext.thermal_core.config import SceneThermalConfig
        from ext.thermal_core.specs import UniformTempSpec
        from ext.thermal_core.operations import ClampOp
        from ext.thermal_core.pipeline import BakingPipeline
        from ext.thermal_core.op_registry import OpRegistry
        from ext.thermal_core.field import MeshSample

        config = SceneThermalConfig(
            sources={"Cube": UniformTempSpec(value_k=300.0)},
            operations=(ClampOp(min_k=0.0, max_k=295.0),),
        )
        config.validate()

        sample = MeshSample.build(
            positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
            edges=np.array([[0, 1], [1, 2]], dtype=np.int32),
        )

        result = BakingPipeline.evaluate(
            config, {"Cube": sample}, apply_operation=OpRegistry.apply,
        )
        assert not result.failures, result.failures
        values = result.fields.field_for("Cube").values
        assert np.allclose(values, 295.0), values
        assert "bpy" not in sys.modules
        print("OK")
        """
    )
    _assert_ok(result)


def test_unregister_without_register_is_a_no_op():
    result = _run_without_bpy(
        """
        import ext
        ext.unregister()
        ext.unregister()
        print("OK")
        """
    )
    _assert_ok(result)


