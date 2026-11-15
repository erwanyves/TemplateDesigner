# TemplateDesigner — TechDraw template editor for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-tested_on_26.3-orange.svg)](https://www.freecad.org)
[![Version](https://img.shields.io/badge/version-0.2.2-green.svg)](#version-history)

Opens a TechDraw template (an SVG file), shows it as TechDraw will, and lets you move, add and edit its texts, editable fields, lines, rectangles and logo — with the mouse and with numeric fields — then saves it to your own templates folder.

**Author:** Yves Guillou · **Version:** 0.2.2 · **License:** LGPL v2.1

---

## Features

- **Start from an existing template.** Open any template shipped with FreeCAD or one of yours. Templates shipped with FreeCAD are never modified: saving always goes to your own folder.
- **What you see is what TechDraw shows.** The preview uses the Qt SVG renderer, the engine TechDraw itself uses for templates.
- **Mouse editing.** Click to select, drag to move, drag on empty space to select an area, Ctrl+click to add or remove. Moves snap to a step (0.5 mm by default); Alt moves freely, Shift keeps the move horizontal or vertical. Arrow keys nudge by one step, Shift+arrows by ten.
- **Your FreeCAD navigation style.** Panning and zooming in the preview follow the navigation style chosen in FreeCAD (Gesture, CAD, Blender, OpenInventor, OpenCascade, Touchpad…), adapted to a 2D sheet exactly as TechDraw adapts it to its pages, with your zoom direction, zoom step and zoom-at-cursor settings. The left button stays for selecting and moving. A right click opens a context menu (edit, insert, undo). The active style and its gestures are shown in the Properties panel when nothing is selected.
- **Numeric editing.** Position, size, font height, font, alignment and line width of the selected element in a side panel.
- **Editable fields.** Turn any text into a TechDraw editable field, name it, pick an autofill (author, date, scale, sheet…). The macro writes what TechDraw needs — a `freecad:editable` attribute, a `<tspan>` and an `id` — and refuses two fields with the same name.
- **Insert.** Fixed text, editable field, line, rectangle, logo (PNG, JPEG or SVG, embedded in the template).
- **New template.** A sheet frame built like the ISO 5457 templates shipped with FreeCAD (drawing frame, centring marks, grid reference system, trimming marks), A4 to A0, landscape or portrait, with a title block from the library.
- **Change sheet size.** For templates with that structure, the frame is rebuilt for the new size and the title block follows the bottom-right corner of the drawing frame. Elements that no longer fit are listed, not altered.
- **Title block library.** The five ISO 7200 title blocks shipped with FreeCAD, plus your own: select the title block of any template and export it, then reuse it on any sheet size.
- **Undo / redo** of every edit (100 steps).
- **Checked before saving.** Anything that would stop TechDraw from reading a field (missing `id`, missing `<tspan>`, duplicate name) is listed before the file is written.
- **FreeCAD integration, on request only.** Apply the template to a TechDraw page while keeping the values already typed in fields of the same name; set it as the TechDraw default template; declare your folder as the TechDraw template folder. Each command tells what it changed.

---

## Requirements

- FreeCAD with the TechDraw workbench. Developed and bench-tested with **FreeCAD 26.3** (Qt 6). Written to run on FreeCAD 1.0 and later (PySide2 or PySide6), but not yet tested on those versions; with Qt 5 builds, text outlines in the preview are estimated from the font size instead of measured.
- No external dependency

---

## Installation

Copy `TemplateDesigner.FCMacro` and the `TemplateDesigner/` folder into your FreeCAD macro directory (shown in **Macro → Macros…**).

```
Macro/
├── TemplateDesigner.FCMacro     ← entry point, the file you run
└── TemplateDesigner/            ← macro code, translations (en, fr), title blocks
```

---

## Usage

1. Run **TemplateDesigner.FCMacro**. No selection is needed.
2. Choose what to start from: a FreeCAD template, one of your templates, or a new one.
3. Edit: drag elements, use the **Insert** menu, adjust values in the **Properties** panel. The **Editable fields** tab lists every field with its autofill and default value.
4. **Save.** The first save of a FreeCAD template asks for a name in your templates folder.
5. Optionally, in the **FreeCAD** menu: apply the template to a page, set it as default, or declare your folder to TechDraw.

### Where templates are saved

By default in a `Templates` folder next to the macro directory (`%APPDATA%\FreeCAD\Templates` on a standard Windows installation), shared by all FreeCAD versions. Change it with **File → My templates folder…**. Exported title blocks go to its `cartouches` subfolder.

### Changing the sheet size of an older template

Templates that do not follow the ISO 5457 structure (no frame identified as `drawing_space_frame`) cannot be resized automatically: the macro cannot tell the frame from the title block, and does not guess. Select the title block elements (drag an area around them), use **Template → Export selection as title block…**, then create a new template of the wanted size with that title block.

---

## What the macro writes

- **SVG files** in your templates folder — never in the FreeCAD installation folder.
- **A TechDraw page**, only with **FreeCAD → Apply to a TechDraw page…**: the template file of the page is replaced, in a single undo step, and field values with matching names are put back. Note that undoing this step in FreeCAD restores the previous template with its default values, not the values you had typed (FreeCAD behaviour); redo brings them back.
- **Two TechDraw preferences**, only with the corresponding commands: `TemplateFile` (default template) and `TemplateDir` (template folder). The previous value is shown.

---

## Limits

- Elements are moved with the mouse; rectangles, lines and logos are resized with numeric fields, not with handles.
- Only two-point lines have editable end points; other paths can be moved but not reshaped.
- The frame generator reproduces the six ISO 5457 frames shipped with FreeCAD (A4 landscape and portrait, A3 to A0 landscape) exactly; portrait frames other than A4 follow the same rules but have no reference to compare with. It has not been checked against the text of ISO 5457.
- On a sheet size change, everything that is not the frame follows the bottom-right corner — including an element you placed elsewhere on the sheet.
- Title blocks whose elements refer to each other by id (gradients, patterns, clip paths, symbols: `url(#…)`, `href="#…"`) are refused on insertion and export, rather than copied with broken references. None of the FreeCAD templates is affected.
- Fonts: the preview shows a template with the fonts installed on the computer; `osifont`, used by FreeCAD templates, is loaded from the FreeCAD installation.

---

## Language

English and French. The language follows FreeCAD, then the system; to force one, write its two-letter code in `TemplateDesigner/lang.txt`.

---

## Credits

The title blocks in `data/cartouches/` and the frame layout come from the ISO 5457 / ISO 7200 templates shipped with FreeCAD, by Benjamin May, released under CC0.

---

## Version history

- **0.2.2** — a value typed in the Properties panel and not yet confirmed (no Enter, no change of field) is applied before saving, exporting or applying to a page; it was lost when saving with Ctrl+S or the toolbar button.
- **0.2.1** — wheel zoom now keeps the point under the pointer fixed (it zoomed from the sheet's top-left corner).
- **0.2** — navigation follows the FreeCAD navigation style (as in TechDraw pages); right-click context menu; arrow keys scroll the view when nothing is selected.
- **0.1** — first version: open, edit with mouse and numeric fields, editable fields and autofill, logo, new template, sheet size change, title block library, apply to a page, TechDraw preferences.

---

## License

Licensed under the **GNU Lesser General Public License v2.1**.
