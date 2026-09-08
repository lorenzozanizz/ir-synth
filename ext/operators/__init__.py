""" A module containing all operators which the Blender interface
calls. The operators use both UI elements and elements of the BPY-free
backend.

Any hook that will be implemented will make use of some of the infrastructure
in this module.
"""


from .baking import BakeTemperatureOperator
from .visualization import (VisualizeTemperatureOperator, FitDisplaySpanOperator,
                            ShowColorBarOperator, HideColorBarOperator)
from .environment import AddEnvironmentFactorOperator, RemoveEnvironmentFactorOperator
from .gradient_points import SetGradientPointFromCursorOperator, VisualizeGradientPointsOperator
from .stack import (AddOperationOperator, RemoveOperationOperator, MoveOperationOperator,
                    DuplicateOperationOperator, IsolateOperationOperator,
                    AddScopeObjectOperator, RemoveScopeObjectOperator)

classes = (
    BakeTemperatureOperator,
    VisualizeTemperatureOperator,
    FitDisplaySpanOperator,
    HideColorBarOperator,
    ShowColorBarOperator,
    AddEnvironmentFactorOperator,
    AddOperationOperator, RemoveOperationOperator, MoveOperationOperator,
    DuplicateOperationOperator, IsolateOperationOperator,
    AddScopeObjectOperator, RemoveScopeObjectOperator,
    RemoveEnvironmentFactorOperator,
    SetGradientPointFromCursorOperator,
    VisualizeGradientPointsOperator,
)
