"""
Bpy-facing orchestration for baking the scene's temperature field into a
per-vertex float mesh attribute.

The bake runs in four separate steps:

    1. build a SceneThermalConfig from bpy   (ui.resolution.ConfigBuilder)
    2. sample the geometry it refers to      (MeshSampler)
    3. evaluate it                           (thermal_core.pipeline)
    4. write the results back onto the meshes

Only steps 1, 2 and 4 touch bpy. A hook replaces step 1 with a config of its
own and reuses the rest unchanged.
"""

from enum import Enum, auto
from typing import Dict, Optional, Tuple

import numpy as np
from bpy.types import Operator, Object

from .names import Labels
from ..constants import (
    TEMPERATURE_ATTR_NAME, TEMPERATURE_ATTR_TYPE, TEMPERATURE_ATTR_DOMAIN,
)
from ..thermal_core.config import SceneThermalConfig
from ..thermal_core.field import FieldSet, MeshSample, ObjectKey
from ..thermal_core.op_registry import OpRegistry
from ..thermal_core.pipeline import FailureReason, PipelineResult, BakingPipeline
from ..ui.resolution import ConfigBuilder


class BakeOutcome(Enum):
    """ Per-object result of an attempted bake, used to build the end-of-run
    summary rather than reporting every object individually.
    """
    BAKED = auto()
    SKIPPED_NOT_MESH = auto()
    SKIPPED_UNRESOLVED = auto()
    SKIPPED_INVALID_SPEC = auto()
    SKIPPED_MISSING_VERTEX_GROUP = auto()
    SKIPPED_NOT_IMPLEMENTED = auto()
    SKIPPED_WRITE_FAILED = auto()


# How a pipeline-stage failure is reported to the user. The mapping
# is (up to now) 1 to 1
_REASON_TO_OUTCOME = {
    FailureReason.INVALID_SPEC: BakeOutcome.SKIPPED_INVALID_SPEC,
    FailureReason.NOT_IMPLEMENTED: BakeOutcome.SKIPPED_NOT_IMPLEMENTED,
    FailureReason.MISSING_GEOMETRY: BakeOutcome.SKIPPED_MISSING_VERTEX_GROUP,
    FailureReason.OPERATION_FAILED: BakeOutcome.SKIPPED_INVALID_SPEC,
}


class MeshSampler:
    """ Extracts a bpy Object's geometry into a bpy-free MeshSample. """

    @staticmethod
    def extract_vertex_group_weights(obj: Object, vertex_group_name: str) -> np.ndarray:
        """ Reads vertex_group_name's per-vertex weight into an array aligned to
        obj.data.vertices. Vertices that aren't members of the group get 0.0,
        matching how weight-paint remapping treats "unpainted" as the bottom of
        the range.

        :raises KeyError: obj has no vertex group named vertex_group_name.
        """
        vertex_group = obj.vertex_groups[vertex_group_name]  # raises KeyError if absent
        # the vertex group has to have been created beforehand
        weights = np.zeros(len(obj.data.vertices), dtype=np.float64)
        # TODO: Optimize this loop somehow.
        for vertex in obj.data.vertices:
            try:
                weights[vertex.index] = vertex_group.weight(vertex.index)
            except RuntimeError:
                pass
        return weights

    @staticmethod
    def extract_positions(obj: Object) -> np.ndarray:
        """ Reads obj's vertex coordinates into an (N, 3) float64 array in WORLD
        space, since operations that read two objects at once need a shared frame.
        """
        mesh = obj.data
        vertex_count = len(mesh.vertices)

        flat = np.empty(vertex_count * 3, dtype=np.float64)
        mesh.vertices.foreach_get('co', flat)
        local = flat.reshape(vertex_count, 3)

        # matrix_world is a 4x4 row-major affine transform; world = R @ p + t.
        matrix = np.array(obj.matrix_world, dtype=np.float64)
        return local @ matrix[:3, :3].T + matrix[:3, 3]

    @staticmethod
    def extract_edges(obj: Object) -> np.ndarray:
        """ Reads obj's edges into an (E, 2) int32 array of vertex indices. """
        mesh = obj.data
        edge_count = len(mesh.edges)

        flat = np.empty(edge_count * 2, dtype=np.int32)
        mesh.edges.foreach_get('vertices', flat)
        return flat.reshape(edge_count, 2)

    @staticmethod
    def sample(obj: Object, vertex_group_name: Optional[str] = None) -> MeshSample:
        """ Build the complete MeshSample for one mesh object.

        :param vertex_group_name: name of the vertex group whose weights the
            resolved spec needs, or None. Weights are read only when asked
            for, since that loop is the expensive part of sampling.
        :raises KeyError: vertex_group_name was given but obj has no such group.
        """
        weights = (
            None if vertex_group_name is None
            else MeshSampler.extract_vertex_group_weights(obj, vertex_group_name)
        )
        return MeshSample(
            vertex_count=len(obj.data.vertices),
            positions=MeshSampler.extract_positions(obj),
            edges=MeshSampler.extract_edges(obj),
            vertex_group_weights=weights,
        )

    @staticmethod
    def sample_for_config(
        objects: Dict[ObjectKey, Object], config: SceneThermalConfig,
    ) -> Tuple[Dict[ObjectKey, MeshSample], Dict[ObjectKey, BakeOutcome]]:
        """ Sample every object the config names.

        The config is consulted first because which vertex group to read - if
        any - is a property of the resolved spec.

        :param objects: object key -> the bpy Object it came from.
        :return: (samples, per-object failures)
        """
        samples: Dict[ObjectKey, MeshSample] = {}
        failures: Dict[ObjectKey, BakeOutcome] = {}

        for key, spec in config.sources.items():
            obj = objects.get(key)
            if obj is None:
                failures[key] = BakeOutcome.SKIPPED_UNRESOLVED
                continue
            try:
                samples[key] = MeshSampler.sample(obj, spec.get_vertex_group())
            except KeyError:
                failures[key] = BakeOutcome.SKIPPED_MISSING_VERTEX_GROUP

        return samples, failures


class AttributeWriter:
    """ Writes evaluated fields back onto their meshes. """

    @staticmethod
    def write_one(obj: Object, values: np.ndarray) -> None:
        """ Writes values (aligned to obj.data.vertices) into the
        TEMPERATURE_ATTR_NAME point-domain float attribute, creating it if
        absent. Re-baking is idempotent; a name collision with a wrong-typed
        attribute is an error.
        """
        mesh = obj.data
        attribute = mesh.attributes.get(TEMPERATURE_ATTR_NAME)
        if (attribute is not None and (
                attribute.data_type != TEMPERATURE_ATTR_TYPE
                or attribute.domain != TEMPERATURE_ATTR_DOMAIN)):
            raise RuntimeError(
                f"{obj.name!r} already has an attribute named "
                f"{TEMPERATURE_ATTR_NAME!r} of type {attribute.data_type!r} on the "
                f"{attribute.domain!r} domain, but the temperature field needs "
                f"{TEMPERATURE_ATTR_TYPE!r} on {TEMPERATURE_ATTR_DOMAIN!r}. "
                f"Rename or remove the conflicting attribute."
            )
        if attribute is None:
            # If the attribute does not exist yet, create it, otherwise just set it.
            attribute = mesh.attributes.new(
                name=TEMPERATURE_ATTR_NAME,
                type=TEMPERATURE_ATTR_TYPE,
                domain=TEMPERATURE_ATTR_DOMAIN,
            )
        # The core computes in float64 which we convert to fp32, where the
        # values stop being numbers and become mesh data.
        attribute.data.foreach_set('value', np.ascontiguousarray(values, dtype=np.float32))
        mesh.update()

    @staticmethod
    def write_all(
        objects: Dict[ObjectKey, Object], fields: FieldSet,
    ) -> Dict[ObjectKey, BakeOutcome]:
        """ Write every field in the set. One failed write does not stop the rest.
        The object key is only used to index into the outcome dictionary.

        :return: object key -> outcome, for every key attempted.
        """
        outcomes: Dict[ObjectKey, BakeOutcome] = {}
        for key, field in fields.items():
            obj = objects.get(key)
            if obj is None:
                outcomes[key] = BakeOutcome.SKIPPED_UNRESOLVED
                continue
            try:
                AttributeWriter.write_one(obj, field.values)
                outcomes[key] = BakeOutcome.BAKED
            except RuntimeError:
                outcomes[key] = BakeOutcome.SKIPPED_WRITE_FAILED
        return outcomes


class SceneBakeRunner:
    """ The four-step bake, kept separate from the Operator so it can be driven
    by anything agnostic from bpy like a hook, a batch script, or a test
    """

    @staticmethod
    def run(scene) -> Dict[ObjectKey, BakeOutcome]:
        """ Bake every mesh object in the scene.

        :return: object key -> outcome, for every mesh object considered.
        """
        # Currently, just a name: obj mapping
        objects = {
            ConfigBuilder.object_key(obj): obj for obj in ConfigBuilder.mesh_objects(scene)
        }

        # 1. bpy -> config
        config, unresolved, invalid = ConfigBuilder.from_scene(scene)
        outcomes: Dict[str, BakeOutcome] = {
            key: BakeOutcome.SKIPPED_UNRESOLVED for key in unresolved
        }
        # 2. bpy -> geometry
        # Extract the geometry at bake time to be employed for modifiers.
        samples, sample_failures = MeshSampler.sample_for_config(objects, config)
        outcomes.update(sample_failures)

        # 3. pure evaluation
        pipeline = BakingPipeline()
        result = pipeline.evaluate(
            config,
            samples,
            apply_operation=OpRegistry.apply,
            collections=ConfigBuilder.collection_membership(objects.values()),
        )
        outcomes.update(SceneBakeRunner._outcomes_from_failures(result))

        # 4. back onto the meshes
        outcomes.update(AttributeWriter.write_all(objects, result.fields))
        return outcomes

    @staticmethod
    def _outcomes_from_failures(result: PipelineResult) -> Dict[ObjectKey, BakeOutcome]:
        """ Map the pipeline's per-object failures onto reportable outcomes.

        Scene-level failures carry no key and are not attributable to one
        object, so they are dropped here and surfaced by the summary instead.
        """
        return {
            failure.key: _REASON_TO_OUTCOME.get(failure.reason, BakeOutcome.SKIPPED_INVALID_SPEC)
            for failure in result.failures if failure.key is not None
        }


class BakeTemperatureOperator(Operator):
    """ Resolves every mesh object in the scene's effective temperature-init
    spec and bakes it into a per-vertex TEMPERATURE_ATTR_NAME float attribute
    (see constants.py).

    Objects that fail to resolve, use a not-yet-implemented strategy or
    reference a missing vertex group are skipped rather than blocking the
    entire scene bake.
    """
    bl_idname = Labels.BAKE_TEMPERATURE.value
    bl_label = "Bake Initial Temperature"
    bl_description = (
        "Resolve and bake every mesh object's initial-temperature spec "
        "into a per-vertex mesh attribute for shading"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        outcomes = SceneBakeRunner.run(context.scene)

        # Report if any baking has failed (this can happen for multiple reasons, see any
        # BakeOutcome != BAKED)
        any_baked = any(outcome is BakeOutcome.BAKED for outcome in outcomes.values())
        any_skipped = any(outcome is not BakeOutcome.BAKED for outcome in outcomes.values())

        self.report({'WARNING'} if any_skipped else {'INFO'}, self.make_summary(outcomes))

        return {'FINISHED'} if any_baked or not any_skipped else {'CANCELLED'}

    @staticmethod
    def make_summary(outcomes: Dict[ObjectKey, BakeOutcome]) -> str:
        """ Builds the one-line final report. Non-mesh objects never reach the
        outcome map, so nothing has to be filtered out here.
        """
        baked = sum(1 for outcome in outcomes.values() if outcome is BakeOutcome.BAKED)
        skipped = [
            outcome for outcome in outcomes.values() if outcome is not BakeOutcome.BAKED
        ]

        if not skipped:
            return f"Baked {baked} object(s)"

        counts: Dict[BakeOutcome, int] = {}
        for outcome in skipped:
            counts[outcome] = counts.get(outcome, 0) + 1
        detail = ", ".join(
            f"{count} {outcome.name.replace('SKIPPED_', '').replace('_', ' ').title()}"
            for outcome, count in counts.items()
        )
        return f"Baked {baked} object(s); skipped {len(skipped)}: {detail}"


class DiffuseTemperatureOperator(Operator):
    """ Modal operator to diffuse temperature across objects allowing potential UNDO
    capabilities. Not yet implemented.
    """

    pass


class EvolveTemperatureOperator(Operator):
    """ Not yet implemented """
    pass
