""" A file containing all the labels assigned to all operations inside the extension.
Note that the labels are divided by class and file, as to find them easily.

The labels are used around the other folders to avoid spreading "magic strings" and
to prevent dead-link operators which Blender cannot render and have no effect.

When a class requires to draw the corresponding property operator, it can access the
label as Labels.NAME.value

Operation labels which are terminated with _ are internal operations which are more likely
related to auxiliary GUI (e.g. menu drawing, etc...) although the distinction is
admittedly somewhat fuzzy
"""

from enum import Enum

class Labels(Enum):
    """ This class contains label for all operators used for all actions inside the
    extensions. To access an operator's use Labels.NAME.value
    """

    # ------------- Default namespace names ---------------
    # |
    # ( Default operator to open a URL.  )
    OPEN_URL                = "wm.url_open"

    # ------------- Names inside "thermal" (baking family) ---------------
    # |
    # ( Resolves each mesh object's TempInitSpec and bakes it into
    #   a per-vertex float mesh attribute. )
    BAKE_TEMPERATURE        = "thermal.bake_temperature"
    # ( Reserved for the future modal diffusion operator not yet implemented )
    DIFFUSE_TEMPERATURE_     = "thermal.diffuse_temperature"
    # ( Reserved for the future time-evolution operator, not yet implemented )
    EVOLVE_TEMPERATURE_      = "thermal.evolve_temperature"


    # ------------- Names inside "thermal" (visualization family) ---------------
    # |
    # ( Builds/updates the shared "Thermal Visualization" material and
    #   assigns it to every baked mesh object. )
    VISUALIZE_TEMPERATURE    = "thermal.visualize_temperature"
    # ( Sets the false-colour display span to the range of the baked field )
    FIT_DISPLAY_SPAN         = "thermal.fit_display_span"
    # ( Visualize the left-bottom color bar )
    SHOW_COLOR_BAR           = "thermal.show_color_bar"
    # ( Hide the left-bottom color bar )
    HIDE_COLOR_BAR           = "thermal.hide_color_bar"

    # ------------- Names inside "thermal" (operation stack family) ---------------
    # |
    # ( Appends an entry of a given OpType to the scene's operation stack. )
    OP_STACK_ADD             = "thermal.op_stack_add"
    # ( Deletes the entry at a given index. )
    OP_STACK_REMOVE          = "thermal.op_stack_remove"
    # ( Shifts the entry at a given index up or down by one position. )
    OP_STACK_MOVE            = "thermal.op_stack_move"
    # ( Inserts a copy of the entry at a given index just below it. )
    OP_STACK_DUPLICATE       = "thermal.op_stack_duplicate"
    # ( Expands one entry and collapses the rest. Used by the per-object
    #   shortcut to point at an operation in the scene stack. )
    OP_STACK_ISOLATE         = "thermal.op_stack_isolate"
    # ( Appends an empty object slot to one operation scope. )
    OP_SCOPE_OBJECT_ADD      = "thermal.op_scope_object_add"
    # ( Deletes one object slot from one operation scope. )
    OP_SCOPE_OBJECT_REMOVE   = "thermal.op_scope_object_remove"
    # ( Menu listing every registered operation, grouped by category. )
    ADD_OPERATION_MENU_      = "thermal.op_add_operation"


    # ------------- Names inside "thermal" (environment family) ---------------
    # |
    # ( Appends a new entry to the scene's environmental-factor stack )
    ENVIRONMENT_FACTOR_ADD    = "thermal.environment_factor_add"
    # ( Removes an entry from the scene's environmental-factor stack )
    ENVIRONMENT_FACTOR_REMOVE = "thermal.environment_factor_remove"

    # ------------- Names inside "thermal" (gradient editing family) ---------------
    # |
    # ( Copies the 3D cursor's world position into a Gradient point field )
    GRADIENT_POINT_FROM_CURSOR = "thermal.gradient_point_from_cursor"
    # ( Toggles the 3D-viewport overlay showing the gradient's two points and axis )
    VISUALIZE_GRADIENT_POINTS  = "thermal.visualize_gradient_points"
