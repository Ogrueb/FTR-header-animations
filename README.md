# Windows file-operation header animations (FTR / "Fluster"): renders and toolkit

The six animations played in the header of the Windows Vista / 7 / 10 file-operation progress dialog, decoded from their original vector data (shell32 resource type `FTR`, IDs 200–205) and rendered by an independent renderer. Validated against 1:1 screen recordings on Vista, Windows 7 and Windows 10 with no fitting: median error 1.0–1.6 levels out of 255 on lossless Windows 7 captures, 1.8–3.8 on compressed captures.

## Downloads

The renders are attached to the [latest release](https://github.com/Ogrueb/FTR-header-animations/releases/latest) as two zips with the same layout and file names; pick one, or both.

| File | Contents |
|---|---|
| `FTR_header_animations_exports_gdiplus_2026-10-08.zip` | the renders **as Windows drew them** (`gdiplus` model) |
| `FTR_header_animations_exports_geometric_2026-10-08.zip` | the renders **as the shapes describe them** (`geometric` model) |

This repository holds the rest: `docs/format_and_player.md` (file format, how the player draws, timing, dialog layout, validation), `toolkit/` (resource extractor, parser, renderer with both models, export scripts, dialog trigger scripts) and `validation/` (recordings vs renders). The toolkit reproduces either export set (apart from rare one-level rounding differences between machines).

## Choosing an export set

- **gdiplus:** the most accurate reproduction of the real dialog, including GDI+'s own quirks. Use it to restore or emulate the dialog.
- **geometric:** the vector shapes drawn as the file describes them, free of GDI+'s implementation artefacts. Use it when the animation is treated as artwork.

| | `geometric` | `gdiplus` |
|---|---|---|
| Antialiasing | 4 × 4 samples per pixel, centred | 8 × 4 samples aligned to the pixel corner, as GDI+ |
| Curves | ~1.5 px segments | ~0.25 px segments |
| Thin pens (all pens in these files) | round-capped stroke, at least 1 px wide | GDI+'s one-pixel line: one pixel per step along the line, ends extended 0.25 px |
| Wider pens | round-capped stroke | widened outline with miter joins and round caps |
| Radial gradients | centred on the ellipse | centre shifted R/13, as GDI+'s path-gradient brush |
| Transparency multiplier | exact fraction | applied to the 0–255 alpha and truncated, as the player does |
| Error against lossless recordings (201 / 202 / 203) | 2.42 / 2.41 / 3.82 | 1.03 / 1.21 / 1.63 |

On screen the difference is subtle: slightly crisper one-pixel outlines in `gdiplus`, and its glows in 200 and 204 sit a little off-centre, as on Windows. A further-refined variant (finer antialiasing and curves, lines at their exact authored width) was evaluated and not included: the refinements were invisible except for thinner, fainter outlines that also moved further from the original.

## Export layout (both zips)

```
animations/<id>_<name>/                    200_generic … 205_delete
    <name>_400x40_transparent.png          APNG, transparent background (straight alpha)
    <name>_400x40_transparent_png/         the same as one PNG per frame
    <name>_400x40_win7.png / .gif          over the Windows 7/10 header gradient
    <name>_400x40_vista.png / .gif         over the Windows Vista header gradient
    (the same again at 800x80)
    header_strips/                         complete header strips with text, Win7/10 and Vista styles
    realspeed_21.33fps/                    the animated files again at the speed Windows actually plays
```

Sizes: 400×40 is the original size at 100% display scaling; 800×80 is a true 200% render (4K-readable), not an enlargement. Other sizes: `toolkit/export.py --sizes WxH`.

| ID | Shown for | Frames |
|---|---|---|
| 200 generic | processing, downloading, uploading, calculating, searching, renaming, formatting; also MTP (phone) copies on Windows 10 | 140 |
| 201 copy | copying | 59 |
| 202 move | moving | 87 |
| 203 properties | applying properties | 87 |
| 204 recycle | recycling (delete to Recycle Bin) | 87 |
| 205 delete | deleting permanently | 87 |

## Timing

The files declare 24 fps, and the main exports use exactly that (41.67 ms per frame). Windows actually plays them at **21.33 fps**: the player asks for a 41 ms timer, which Windows rounds up to its default 15.625 ms tick, giving 46.875 ms per frame. The `realspeed_21.33fps/` copies use 46.875 ms. On a system where another program has raised the timer resolution, the dialog runs at about 24.4 fps. GIF can only store whole hundredths of a second: the 24 fps GIFs use 40 ms, and the real-speed GIFs alternate 40/50 ms to keep the exact average.

## Header strips

Recreations of the whole 400×40 header: gradient, animation and the text `<Operation> 45 items (450 MB)`.
- **win7 style** (Windows 7 and 10): black text drawn over the animation.
- **vista style:** teal/green gradient, white text drawn under the animation.

Both stacking orders were measured on recordings. The text is Segoe UI 12 pt, drawn at its final pixel size with the font's hinting, as Windows draws it: on lossless Windows 7 recordings its letter shapes, spacing and position match the real dialog to the pixel. Windows adds ClearType's colour fringes, which depend on the monitor; the strips use greyscale antialiasing, which looks right on any screen. To make strips with other text, run `toolkit/strip.py` with a Segoe UI font file (not included). It places letters with Pillow's BASIC layout engine, which matches Windows' spacing but does not shape scripts such as Arabic or Devanagari.

## Toolkit

**What you need to supply:**
- **The animation data:** a copy of `shell32.dll` from Windows Vista or 7 (`C:\Windows\System32`), or `C:\Windows\SystemResources\shell32.dll.mun` from Windows 10. Windows 11 24H2 no longer contains the animations. The data is Microsoft's, so it isn't included; `extract_ftr.py` pulls the six resources out and checks them against the checksums in `docs/format_and_player.md`.
- **Python 3** with NumPy and Pillow (SciPy only for `fit.py`).
- **Segoe UI** (`segoeui.ttf` from `C:\Windows\Fonts`), only for header strips.

**Files:**
- `extract_ftr.py`: extracts FTR 200–205 from a shell32 file and verifies them (standard library only).
- `ftr.py`: parser.
- `render.py`, `timeline.py`: renderer and timeline (`render.MODEL = 'gdiplus'` or `'geometric'`).
- `compose.py`: header gradients.
- `export.py`: transparent and composited exports at any size, with `--model`, and `--frame-ms 46.875` for real speed.
- `strip.py`: header strips with text.
- `crop.py`, `fit.py`: validation against screen recordings.
- `show_progress_dialog.ps1` (Windows 7/10) and `.cs` (Vista/7; compile with the .NET 2.0 `csc.exe`): open the real progress dialog with any animation, for reference recordings.

```
python toolkit/extract_ftr.py shell32.dll ftr_data
python toolkit/export.py ftr_data/ftr_201_copy.bin out --name copy --sizes 400x40,800x80 --model gdiplus
python toolkit/strip.py ftr_data/ftr_201_copy.bin out --font segoeui.ttf --text "Copying 3 items (12 MB)" --model geometric
```

`extract_ftr.py` writes `ftr_200_generic.bin`, `ftr_201_copy.bin`, `ftr_202_move.bin`, `ftr_203_apply_properties.bin`, `ftr_204_recycle.bin` and `ftr_205_delete.bin`. The published sets use `--name` generic, copy, move, properties, recycle and delete, and the strip text `<Operation> 45 items (450 MB)` (200 uses "Downloading").

## Licence

The toolkit (`toolkit/`) and the documentation in this repository are licensed under the GNU Affero General Public License, version 3 or (at your option) any later version: see `LICENSE` (SPDX: `AGPL-3.0-or-later`). Each source file carries an SPDX header.

The licence does not cover Microsoft's material: the FTR animation data (not included; you extract it from your own Windows files), the renders made from it, the Segoe UI font, or the Windows screen captures in `validation/`.
