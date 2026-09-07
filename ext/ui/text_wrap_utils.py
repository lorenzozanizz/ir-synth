import bpy


class WrapWidget:

    # Based on my implementation inside
    # https://github.com/lorenzozanizz/rendersynth/blob/main/ext/ui/description.py

    @staticmethod
    def wrap_with_hyphens(text, width):
        """Break text at width boundary, adding hyphen if breaking mid-word"""
        if len(text) <= width:
            return [text]

        lines = []
        remaining = text

        while remaining:
            if len(remaining) <= width:
                lines.append(remaining)
                break

            last_space = remaining[:width].rfind(' ')

            if last_space > width * 0.35:  # If space is in last 40% of line
                lines.append(remaining[:last_space])
                remaining = remaining[last_space + 1:]
            else:
                lines.append(remaining[:width - 1] + '-')
                remaining = remaining[width - 1:]

        return lines

    @staticmethod
    def draw(layout, context, message: str, icon: str='INFO'):

        # Sanitize the string, only double \n\n count as newline.
        message = message.replace('    ', '')
        message = message.replace("\n\n", "@")
        message = message.replace('\n', ' ')
        message = message.replace('@', '\n')

        # Get the 3D View area and panel width
        panel_width = 250  # fallback
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'UI':
                            panel_width = region.width
                            break
        except:
            pass

        ui_scale = context.preferences.view.ui_scale
        char_width = 8 * ui_scale
        max_chars = max(20, int((panel_width - 40) / char_width))

        # Create box for description, disable it for the "grey" elegant effect
        box = layout.box()
        box.enabled = False

        for line in message.split('\n'):
            line = line.strip()
            if not line:
                continue

            wrapped = WrapWidget.wrap_with_hyphens(line, max_chars)

            # Draw each wrapped chunk
            for i, chunk in enumerate(wrapped):
                row = box.row()
                row.scale_y = 0.6

                # Only show icon on first chunk of first line, do not show it again every other line
                if i == 0:
                    row.label(text=chunk, icon=icon)
                else:
                    row.label(text=chunk)
        layout.separator()
