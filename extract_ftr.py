# FTR / "Fluster": file format, player behaviour and validation

Technical notes accompanying the renders. The animated strip at the top of the Windows Vista / 7 / 10 file-operation progress dialog is a small vector animation stored in shell32 as resource type `FTR`, in a binary format derived from SWF, and played by DirectUI's `Movie` element through a stripped-down Flash-like player that Microsoft calls "Fluster", drawing with GDI+.

## Where the animations live

| Windows | Location | Resource IDs |
|---|---|---|
| Vista SP2 (x86 6.0.6002.18005) | `shell32.dll`, resource type `FTR` (a named type) | 200–205, language 1033 |
| 7 SP1 (6.1.7601.17514, x64 and x86) | `shell32.dll`, same | same |
| 10 21H2 (19044) | `C:\Windows\SystemResources\shell32.dll.mun` (resources moved out of shell32.dll from 1903 on) | same |
| 11 24H2 (26100) | **removed**: no FTR resources, and the dialog markup has no movie element | — |

All six files are byte-identical across Vista SP2, Windows 7 SP1 and Windows 10 21H2. The resource data is Microsoft's and isn't distributed; `toolkit/extract_ftr.py` extracts it from your own copy of `shell32.dll` or `shell32.dll.mun` and checks it against these checksums:

| ID | File name used by the toolkit | Size | MD5 |
|---|---|---|---|
| 200 | `ftr_200_generic.bin` | 130,000 bytes | `cdc7839a3f818472411b8781a9c63bba` |
| 201 | `ftr_201_copy.bin` | 88,886 bytes | `e7846b9bd5aa6ea5e31f0a0a3de08321` |
| 202 | `ftr_202_move.bin` | 94,461 bytes | `6ee3df8cc7beec637f25dd53faf97913` |
| 203 | `ftr_203_apply_properties.bin` | 123,675 bytes | `179ec7200a61bf90669ab2341f576763` |
| 204 | `ftr_204_recycle.bin` | 120,445 bytes | `8e17feaecbcec87fb7a622ca2c3aee06` |
| 205 | `ftr_205_delete.bin` | 143,946 bytes | `454806ab2f520cae791d204c674c7cb9` |

## Which animation is shown

The dialog picks the animation from the `SPACTION` value its caller passes to `IOperationsProgressDialog::SetOperation` or `IActionProgress::Begin`; shell32's table has 14 rows in `SPACTION` order:

| SPACTION | Header text | FTR |
|---|---|---|
| 0 NONE | Processing | 200 |
| 1 MOVING | Moving | 202 |
| 2 COPYING | Copying | 201 |
| 3 RECYCLING | Recycling | 204 |
| 4 APPLYINGATTRIBS | Applying properties | 203 |
| 5 DOWNLOADING | Downloading | 200 |
| 6 SEARCHING_INTERNET | Searching internet for | 200 |
| 7 CALCULATING | Calculating | 200 |
| 8 UPLOADING | Uploading | 200 |
| 9 SEARCHING_FILES | Searching | 200 |
| 10 DELETING | Deleting | 205 |
| 11 RENAMING | Renaming | 200 |
| 12 FORMATTING | Formatting | 200 |
| 13 COPY_MOVING | Moving | 202 |

That is why a phone (MTP) copy on Windows 10 shows the generic animation 200 under "Copying…" text: the MTP path passes an operation from 200's group, not `SPACTION_COPYING`.

## File format

Little-endian throughout. The record type numbers equal SWF tag codes, but the bodies are not SWF: there are no bit-packed fields, coordinates are floats, and paths are stored as GDI+ point lists.

**Primitives:** color = 4 bytes R, G, B, A. matrix = 6 × f32 in GDI+ order (m11, m12, m21, m22, dx, dy): x' = m11·x + m21·y + dx, y' = m12·x + m22·y + dy. cxform = 4 × (f32 multiplier, f32 add) for R, G, B, A.

**Header:** `i32 left, top, right, bottom` (twips; 0, 0, 8000, 800 in every file) · `f64 frame rate` (24.0) · `u32 record count` · records.

**Records:** `u32 type`, then:

| Type | Name | Body |
|---|---|---|
| 1 | ShowFrame | — |
| 2, 22, 32 | DefineShape | `u16 id` · `u32 n` × (color, `f32` width) line styles · `u32 n` × fill styles · `u32 n` × paths · `u32 n` × (`u32 op`, `i32 arg`) draw list |
| 9 | SetBackgroundColor | color (not used for drawing) |
| 10, 11 | ? | `u16` (not used by shell32's files) |
| 12 | DoAction | `u32`, `u16` (not used) |
| 26 | PlaceObject2 | `u8 isClip, u8 hasCxform, u8 hasMatrix, u8 hasCharacter, u8 move` · `u16 depth` · `u16 characterId` (0xFFFF = none) · `u16 clipDepth` (0xFFFF = none) · [matrix] · [cxform] |
| 28 | RemoveObject2 | `u16 depth` |
| 39 | DefineSprite | `u16 id` · `u32 n` · n records (nested timeline) |

- **Fill style:** `u32 kind`. 0 solid: color. 3 radial and 4 linear: `u32 n` × (color, `f32` position), then a matrix. Kind 2 has a reader in the player (probably a bitmap fill) but no file uses it.
- **Path:** `u32 n` × (`f32 x`, `f32 y`, `u8` GDI+ PathPointType). Point types: 0 start, 1 line, 3 Bézier, in threes.
- **Draw list:** op 1 selects a fill, op 0 a line style (−1 = none), op 2 draws a path by index (fill, then stroke).

The PlaceObject2 flag names were inferred from value statistics and display-list consistency rather than from the disassembly; they play all six files correctly.

| FTR | Frames | Shapes | Sprites |
|---|---|---|---|
| 200 generic | 140 | 8 | 9 |
| 201 copy | 59 | 16 | 9 |
| 202 move | 87 | 38 | 7 |
| 203 properties | 87 | 43 | 12 |
| 204 recycle | 87 | 45 | 12 |
| 205 delete | 87 | 71 | 10 |

## How the player draws

Each point was confirmed in the player's code, on 1:1 recordings, or by replaying the decoded drawing commands through GDI+ itself.

1. **Geometry:** the 8000×800 twip frame fills the 400×40 movie element. It scales with DPI: 700×70 at 175%, 800×80 at 200%.
2. **Device-space drawing:** the player transforms each path to device pixels itself and folds the shape matrix into the brush transform, rather than drawing under a GDI+ world transform. Pen widths scale with the shape matrix.
3. **Pixel grid:** no PixelOffsetMode is set, so GDI+ puts pixel centres on integer coordinates. A renderer that samples at pixel centres (+0.5) must shift the movie by +0.5 device px.
4. **Fills:** even-odd (FillModeAlternate), antialiased (SmoothingMode HighQuality). GDI+ antialiases with 8 × 4 samples per pixel at (i/8, j/4) from the pixel's corner, not centred, so edges land about 1/16 px right and 1/8 px down of where exact-area coverage would put them.
5. **Linear gradients:** a GDI+ line brush from (−16384, 0) to (16384, 0), transformed by the fill matrix, TileFlipXY wrap, no gamma correction, stops via PresetBlend.
6. **Radial gradients:** a path-gradient brush on an ellipse of radius 16384, transformed by the fill matrix. Stop position 0 is the edge and 1 the centre; the colour follows the fraction of the way along the ray from the centre to the ellipse, and nothing is painted outside it (hard edge). GDI+ places the centre at the average of the ellipse path's 13 points, which counts the start point twice: (R/13, 0) in brush space, not (0, 0).
7. **Gradient interpolation happens in premultiplied ARGB.** Interpolating straight colours produces visible halos.
8. **Pens:** round caps. Every pen in these files ends up 0.2–1.3 device px wide, and GDI+ draws any pen up to at least 1.5 px as a one-pixel "nominal" line: one pixel of ink per step along the line's major axis, extended 0.25 px past each end. Wider pens are ordinary widened outlines with miter joins.
9. **Colour transforms:** only the alpha multiplier is used. It multiplies the brush and pen colours' 0–255 alpha, and the product is truncated.
10. **Masks:** a clip layer at depth d with clip depth c masks depths d+1..c inclusive. The mask's drawn paths are merged into one even-odd GraphicsPath and applied with `GdipSetClipPath`, so masks are hard-edged (GDI+ clip regions are not antialiased). Masks nest: the player keeps a clip stack and intersects a new clip with the active one. Two of the six animations are wrong almost everywhere if inner masks are ignored. The mask shapes' own fills are placeholders and never shown.
11. **Timeline:** Flash semantics. A "move" keeps the previous matrix and alpha unless new ones are given; a newly placed sprite shows its first frame at once; child sprites advance before the parent's tags run.

The renderer in `toolkit/` implements all of this. Its `geometric` model omits the GDI+-specific details in points 4, 6 (centre), 8 and 9 and draws the shapes exactly as described by the file; its default `gdiplus` model includes them. The renders are provided in both forms: `gdiplus` as Windows drew it, `geometric` as the shapes describe it.

## Timing

The player converts the declared 24 fps into an integer timer interval, `(int)(1000 / 24)` = 41 ms. Windows timers fire on the system tick, 15.625 ms by default, so frames arrive every 3 ticks = 46.875 ms: **21.33 fps**, which is what every recording shows (Vista, 7 and 10). If another program has raised the timer resolution, the same dialog runs at about 24.4 fps.

## The dialog around the animation

The header is a 400×40 DirectUI element (UIFILE 42 in shell32) with a three-colour horizontal gradient: left edge, midpoint, right edge, linear RGB.

| | Gradient (left → middle → right) | Header text | Stacking |
|---|---|---|---|
| Vista | (9,74,116) → (32,121,140) → (5,111,90) | white | animation drawn over the text |
| 7, 10 | (220,229,244) → (155,192,227) → (0,43,85) | theme's dark text | text drawn over the animation |
| 11 (26100) | as 7 | as 7 | no animation |

## Validation

VirtualBox guests at 96 DPI and 100% scale were recorded 1:1 at 60 fps while the real dialog ran each operation (opened via `IOperationsProgressDialog`), plus a real MTP phone copy on Windows 10. Rendered frames were composited over the exact markup gradient with **no fitting** (fixed placement, no colour correction), and each recorded frame was matched to the best rendered frame, comparing the columns right of the header text. Median RMS error, 0–255 scale:

| OS | Animation | `gdiplus` model | `geometric` model |
|---|---|---|---|
| 7 SP1, lossless 4:4:4 capture | 201 / 202 / 203 | 1.03 / 1.21 / 1.63 | 2.42 / 2.41 / 3.82 |
| 7 SP1, H.264 | 200 / 201 / 202 / 203 / 204 / 205 | 2.27 / 2.86 / 2.89 / 3.78 / 2.71 / 3.00 | 2.73 / 3.47 / 3.42 / 4.95 / 2.82 / 3.16 |
| Vista SP2, H.264 | 200 / 201 | 2.65 / 3.46 | 3.16 / 4.01 |
| 10 21H2, H.264 | 200 (1:1) / 200 (real MTP copy, 175% DPI) | 1.92 / 1.80 | 2.57 / 2.49 |

For comparison, the decoded drawing commands replayed through GDI+ itself score 0.72 / 0.68 / 0.66 on the lossless clips. On compressed clips the remaining differences are dominated by chroma subsampling and compression banding; on lossless clips, by GDI+'s integer arithmetic (±1 level) and a handful of pixels on near-vertical one-pixel lines and gradient ellipse edges. Example comparisons are in `validation/`.
