# TemplateDesigner — TechDraw template editor for FreeCAD

[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)
[![FreeCAD](https://img.shields.io/badge/FreeCAD-tested_on_26.3-orange.svg)](https://www.freecad.org)
[![Version](https://img.shields.io/badge/version-0.2.5-green.svg)](#version-history)

Opens a TechDraw template (an SVG file), shows it as TechDraw will, and lets you move, add and edit its texts, editable fields, lines, rectangles and logo — with the mouse and with numeric fields — then saves it to your own templates folder.

**Author:** Yves Guillou · **Version:** 0.2.5 · **License:** LGPL v2.1

---

## Features

- **Start from an existing template.** Open any template shipped with FreeCAD or one of yours. Templates shipped with FreeCAD are never modified: saving always goes to your own folder.
- **What you see is what TechDraw shows.** The preview uses the Qt SVG renderer, the engine TechDraw itself uses for templates.
- **Mouse editing.** Click to select, drag to move, drag on empty space to select an area, Ctrl+click to add or remove. Moves snap to a step (0.5 mm by default); Alt moves freely, Shift keeps the move horizontal or vertical. Arrow keys nudge by one step, Shift+arrows by ten.
- **Your FreeCAD navigation style.** Panning and zooming in the preview follow the navigation style chosen in FreeCAD (Gesture, CAD, Blender, OpenInventor, OpenCascade, Touchpad…), adapted to a 2D sheet exactly as TechDraw adapts it to its pages, with your zoom direction, zoom step and zoom-at-cursor settings. The left button stays for selecting and moving. A right click opens a context menu (edit, insert, undo). The active style and its gestures are shown in the Properties panel when nothing is selected.
- **Numeric editing.** Position, size, font height, font, alignment, text rotation and line width of the selected element in a side panel.
- **Editable fields.** Turn any text into a TechDraw editable field, name it, pick an autofill (author, date, scale, sheet…). The macro writes what TechDraw needs — a `freecad:editable` attribute, a `<tspan>` and an `id` — and refuses two fields with the same name.
- **Insert.** Fixed text, editable field, line, rectangle, logo (PNG, JPEG or SVG, embedded in the template).
- **Logos keep their proportions.** With **Keep proportions** ticked (the default) in the Properties panel, typing the width of a logo sets its height, and the reverse, from the proportions of the embedded image; the top-left corner stays in place. Untick it to set width and height separately. A logo whose image is not embedded keeps the proportions of its current frame, and the panel says so.
- **New template.** A sheet frame built like the ISO 5457 templates shipped with FreeCAD (drawing frame, centring marks, grid reference system, trimming marks), A4 to A0, landscape or portrait, with a title block from the library.
- **Change sheet size.** For templates with that structure, the frame is rebuilt for the new size and the title block follows the bottom-right corner of the drawing frame. Elements placed in a margin (outside the drawing frame) stay in that margin, at the same distance from the sheet edge and from the nearest end of the frame; a margin text too long for the new margin is made smaller — its length is measured with its font, longest line, as the SVG renderer lays it out — so that it fills the available length, and the change is reported. Elements that no longer fit are listed, not altered.
- **Save a whole family.** **Template → Save the A4 → A0 family…** saves the open template in the ten sizes A4 to A0, portrait and landscape, next to it and named after it (`A4_Portrait-J3D` gives `A3_Landscape-J3D`, `A0_Portrait-J3D`…). Each size is built from the open template, which is not changed; existing files are listed first, and you choose to replace them or keep them.
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
- On a sheet size change, everything inside the drawing frame that is not the frame follows the bottom-right corner — including an element you placed elsewhere in the drawing area. Only elements placed directly on the sheet are sorted between drawing area and margins.
- Title blocks whose elements refer to each other by id (gradients, patterns, clip paths, symbols: `url(#…)`, `href="#…"`) are refused on insertion and export, rather than copied with broken references. None of the FreeCAD templates is affected.
- Margin texts: only a text placed directly on the sheet (not inside a group) is measured and made smaller; a font size given in `pt` is read as user units. The preview, like the Qt SVG renderer it uses, may draw a fractional font size at the whole size below it (3.5 drawn as 3, measured with Qt 6.12), so a reduced text can look shorter than the margin.
- Fonts: the preview shows a template with the fonts installed on the computer; `osifont`, used by FreeCAD templates, is loaded from the FreeCAD installation.

---

## Language

English and French. The language follows FreeCAD, then the system; to force one, write its two-letter code in `TemplateDesigner/lang.txt`.

---

## Credits

The title blocks in `data/cartouches/` and the frame layout come from the ISO 5457 / ISO 7200 templates shipped with FreeCAD, by Benjamin May, released under CC0.

---

## Version history

- **0.2.5** — **Save the A4 → A0 family**: the template in ten sizes, portrait and landscape. On a sheet size change, margin texts stay in their margin and are made smaller when they do not fit; they used to follow the title block into the drawing area.
- **0.2.4** — texts and fields can be rotated (**Rotation** in the Properties panel, in degrees, counter-clockwise as seen on the sheet: 90° reads bottom to top, −90° top to bottom; arrows step by 90°). The text turns about the point where its characters start, which stays in place, and keeps its rotation when moved. For a text placed by a skewed, mirrored or unequally scaled transform (on the text or on a group containing it), the Rotation box is greyed out and the text is left untouched.
- **0.2.3** — logos are resized in proportion: typing the width sets the height, and the reverse, from the proportions of the embedded image (option **Keep proportions** in the Properties panel, ticked by default). The proportions of an SVG logo are read from its viewBox, also when it is inserted; they were rounded to whole units.
- **0.2.2** — a value typed in the Properties panel and not yet confirmed (no Enter, no change of field) is applied before saving, exporting or applying to a page; it was lost when saving with Ctrl+S or the toolbar button.
- **0.2.1** — wheel zoom now keeps the point under the pointer fixed (it zoomed from the sheet's top-left corner).
- **0.2** — navigation follows the FreeCAD navigation style (as in TechDraw pages); right-click context menu; arrow keys scroll the view when nothing is selected.
- **0.1** — first version: open, edit with mouse and numeric fields, editable fields and autofill, logo, new template, sheet size change, title block library, apply to a page, TechDraw preferences.

---

## License

Licensed under the **GNU Lesser General Public License v2.1**.
