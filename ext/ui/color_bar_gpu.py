import bpy
import gpu
# For text drawing
import blf
import math

from gpu_extras.batch import batch_for_shader

from ..constants import DEFAULT_HEAT_PALETTE


class ColorBar:
    """ Fixed 2D colorbar overlay for a Blender 3D Viewport.
    """

    def __init__(self,
        colors: list,
        value_range: tuple,
        position: tuple =(40, 30),
        size: tuple =(25, 250),
        ticks: int =5,
        label: str =None,
    ):
        """ Constructor for the color bar object used to display a color bar
        in the bottom left corner of the viewport.

        :param colors: list of colors to display
        :param value_range: range of values which the colors represent, (low, high)
        :param position: position of the colorbar
        :param size: size of the colorbar
        :param ticks: number of ticks to display
        :param label: label to use
        """
        self.colors = [self._to_rgba(c) for c in colors]

        self.val_min = float(value_range[0])
        self.val_max = float(value_range[1])

        if self.val_min == self.val_max or self.val_max <= self.val_min:
            raise ValueError(
                "ColorBar range must have non-zero size and minimum value < maximum value."
            )

        # Unpack the position and size tuple to use directly in blender GPU calls.
        self.x, self.y = position
        self.width, self.height = size

        self.tick_count = ticks
        self.label = label

        self._handle = None
        self._shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    def show(self):
        """ Display the colorbar in all 3D Viewports """
        if self._handle is not None:
            return

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw, (),
            "WINDOW", "POST_PIXEL",
        )
        # Create the handler, then tag for its redraw at show() time
        self._tag_redraw()

    def is_active(self) -> bool:
        return self._handle is not None

    def hide(self):
        """ Remove the colorbar. This explicitly deletes the drawing
        handler that was created during show(). """
        if self._handle is None:
            return

        bpy.types.SpaceView3D.draw_handler_remove(
            self._handle, "WINDOW",
        )

        self._handle = None
        self._tag_redraw()

    def toggle(self):
        """ Depending on the bar stage, turn off or turn on """
        if self._handle is None:
            self.show()
        else:
            self.hide()

    def update(
        self,
        colors=None,
        value_range=None,
    ):
        """ Update colors and/or numeric range. """
        if colors is not None:
            self.colors = [self._to_rgba(c) for c in colors]

        if value_range is not None:
            self.val_min = float(value_range[0])
            self.val_max = float(value_range[1])

            if self.val_min == self.val_max:
                raise ValueError("ColorBar range must have non-zero size.")

        self._tag_redraw()

    def _draw(self):
        """ Draws the colorbar on the current viewport with
        Blender's 2D graphics utilities. Should NOT be called externally
        and is reserved as callback. """

        # Set the blend for the gradient
        gpu.state.blend_set("ALPHA")

        self._draw_gradient()
        self._draw_border()
        self._draw_ticks()

        if self.label:
            self._draw_label()

        gpu.state.blend_set("NONE")

    def _draw_gradient(self):
        """
        Draw the colorbar as horizontal strips.

        This is deliberately simple and robust. For a typical colorbar
        with 100-500 segments the performance is more than adequate.
        """

        n = max(2, len(self.colors) * 32)

        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n

            y0 = self.y + t0 * self.height
            y1 = self.y + t1 * self.height
            color = self._sample_color(t0)

            vertices = (
                (self.x, y0), (self.x + self.width, y0),
                (self.x + self.width, y1), (self.x, y1),
            )

            batch = batch_for_shader(
                self._shader,
                "TRI_FAN",
                {"pos": vertices},
            )

            self._shader.bind()
            self._shader.uniform_float("color", color)
            batch.draw(self._shader)

    def _draw_border(self):
        """Draw a black/white outline around the colorbar."""

        x0 = self.x
        y0 = self.y
        x1 = self.x + self.width
        y1 = self.y + self.height

        vertices = (
            (x0, y0),
            (x1, y0),
            (x1, y1),
            (x0, y1),
            (x0, y0),
        )

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(
            shader,
            "LINE_STRIP",
            {"pos": vertices},
        )

        shader.bind()
        shader.uniform_float(
            "color",
            (0.0, 0.0, 0.0, 1.0),
        )

        gpu.state.line_width_set(1.5)
        batch.draw(shader)
        gpu.state.line_width_set(1.0)

    def _draw_ticks(self):
        """Draw tick marks and their numeric labels."""

        ticks = self._nice_ticks(
            self.val_min,
            self.val_max,
            self.tick_count,
        )

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        for value in ticks:
            t = (value - self.val_min) / (self.val_max - self.val_min)
            y = self.y + t * self.height

            # Tick line
            vertices = (
                (self.x + self.width, y),
                (self.x + self.width + 6, y),
            )

            batch = batch_for_shader(
                shader,
                "LINES",
                {"pos": vertices},
            )

            shader.bind()
            shader.uniform_float(
                "color",
                (0.0, 0.0, 0.0, 1.0),
            )

            batch.draw(shader)

            # Numeric label
            self._draw_text(
                self.x + self.width + 10,
                y - 5,
                self._format_value(value),
            )

    def _draw_label(self):
        """ Draw the colorbar header label, simply draw its text """
        self._draw_text(
            self.x,
            self.y + self.height + 12,
            self.label,
            size=14,
        )

    def _sample_color(self, t):
        """ Interpolate the supplied color stops at normalized position t. """

        n = len(self.colors)
        if n == 1:
            return self.colors[0]
        t = max(0.0, min(1.0, t))

        scaled = t * (n - 1)
        i = min(int(scaled), n - 2)
        local_t = scaled - i

        c0 = self.colors[i]
        c1 = self.colors[i + 1]

        return tuple(
            a + (b - a) * local_t
            for a, b in zip(c0, c1)
        )

    @staticmethod
    def _to_rgba(color):
        """ Pad a color to RGBA. """
        if len(color) == 3 or len(color) == 4:
            return color if len(color) == 4 else (*color, 1.0)
        raise ValueError("Colors must contain 3 (RGB) or 4 (RGBA) values.")

    @staticmethod
    def _nice_ticks(vmin, vmax, count):
        """Generate approximately count uniformly spaced, visually nice ticks.

        The endpoints are always kept exactly as provided (at most rounded). Interior ticks are
        sampled uniformly and rounded to a sensible precision for display.

        Examples:
            (0, 137, 8) -> [0, 20, 40, 60, 80, 100, 120, 137]
            (-1.0, 1.0, 5) -> [-1.0, -0.5, 0.0, 0.5, 1.0]
        """
        if count <= 1:
            return [vmin]
        if count == 2:
            return [vmin, vmax]
        span = vmax - vmin
        if span == 0:
            return [vmin] * count

        # Uniformly sample the range first.
        step = span / (count - 1)

        # Choose a sensible decimal precision for displaying the step.
        magnitude = 10 ** math.floor(math.log10(abs(step)))

        # Use 1, 2, or 5 × 10^n as the rounding unit.
        normalized = abs(step) / magnitude

        if normalized <= 1:
            nice_step = magnitude
        elif normalized <= 2:
            nice_step = 2 * magnitude
        elif normalized <= 5:
            nice_step = 5 * magnitude
        else:
            nice_step = 10 * magnitude

        # Number of decimal places needed to represent the nice step.
        if nice_step >= 1:
            decimals = 0
        else:
            decimals = max(0, int(-math.floor(math.log10(nice_step))))

        def nice_round(value):
            return round(value, decimals)

        # Keep endpoints exactly unchanged.
        ticks = [vmin]

        # Round only interior ticks.
        for i in range(1, count - 1):
            value = vmin + i * step
            ticks.append(nice_round(value))

        ticks.append(vmax)

        # Rounding can cause two adjacent ticks to become equal. Remove duplicates while
        # preserving the exact endpoints.
        result = [ticks[0]]

        for value in ticks[1:-1]:
            if result[-1] < value < vmax:
                result.append(value)

        result.append(vmax)

        return result

    @staticmethod
    def _format_value(value):
        """ Format tick labels without ugly floating-point artifacts. """
        if abs(value) >= 1000:
            return f"{value:.0f}"
        return f"{value:.3g}"

    @staticmethod
    def _draw_text(x, y, text, size=12):
        """ Draws a given text at the (x,y) coordinates with the string
        contained inside text, and the font size specified by size. Uses the default
        Blender font (corresponding to font-id = 0) to draw text. """
        font_id = 0
        white_color = (1.0, 1.0, 1.0, 1.0)
        blf.size(font_id, size)
        blf.color(font_id, *white_color)

        blf.position(font_id, x, y, 0)
        blf.draw(font_id, str(text))

    @staticmethod
    def _tag_redraw():
        """ Updates all 3d viewports and tags them for redraw after generating the
        color bar for the first time or updating its attributes.

        This affects all 3d viewports.
        """
        for window in bpy.context.window_manager.windows:
            screen = window.screen

            if screen is None:
                continue

            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


# Its a bit bad but we have to instantiate an instance of a color bar
# at the module level so that the information about the registered handler
# is saved somewhere and can be hidden/changed at runtime depending on
# operator calls.
left_bottom_color_bar = ColorBar(
    colors=[
        *DEFAULT_HEAT_PALETTE
    ],
    value_range=(-10.0, 50.0),
    position=(40, 30),
    size=(30, 300),
    ticks=7,
    label="Temperature",
)
