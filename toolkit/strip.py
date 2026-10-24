# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full progress-dialog header strips: gradient + animation + header text (added 6 Oct 2026).

Recreates the 400x40 header as Windows draws it, in two styles measured from 1:1 recordings:

  win7   Windows 7 and 10: Win7 gradient, black text drawn OVER the animation
  vista  Windows Vista: teal/green gradient, white text drawn UNDER the animation

Text: Segoe UI 12 pt (16 px at 100%), origin x = 22, baseline y = 26; all scale with the
output size (800x80 = 200%: 32 px at x = 44, y = 52). The text is drawn at its final pixel
size, so the font's hinting applies, using Pillow's BASIC layout engine, which places letters
at hinted whole-pixel widths as Windows' GDI does (Pillow's Raqm engine, used automatically
when libraqm is installed, places them at unhinted fractional widths). On the lossless Win7
recordings the letter shapes and spacing then match to the pixel. BASIC does no
complex-script shaping (Arabic, Devanagari, ...). Windows adds ClearType's colour fringes; this uses greyscale antialiasing, which
looks right on any screen. The font is NOT included: pass a path to segoeui.ttf
(Windows\\Fonts).

Usage:
  python strip.py FTR OUTDIR --font segoeui.ttf [--text "Copying 45 items (450 MB)"]
                  [--style win7,vista] [--name copy] [--sizes 400x40,800x80]
                  [--frame-ms MS] [--cache DIR] [--model gdiplus|geometric]

Writes <name>_<W>x<H>_<style>_strip.png (APNG) and .gif per style and size. --frame-ms
works as in export.py (46.875 = real Windows speed).
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render                                               # noqa: E402
from timeline import Movie                                  # noqa: E402
from compose import tri_gradient, WIN7, VISTA               # noqa: E402
from export import render_frames, to_u8, save_apng, save_gif  # noqa: E402

STYLES = {
    'win7':  {'colors': WIN7,  'text': (0, 0, 0),       'text_over_movie': True},
    'vista': {'colors': VISTA, 'text': (255, 255, 255), 'text_over_movie': False},
}
TEXT_PX, TEXT_X, TEXT_BASELINE = 16, 22, 26            # pixels at 100% (400x40)
DEFAULT_TEXT = {200: 'Downloading 45 items (450 MB)', 201: 'Copying 45 items (450 MB)',
                202: 'Moving 45 items (450 MB)', 203: 'Applying properties 45 items (450 MB)',
                204: 'Recycling 45 items (450 MB)', 205: 'Deleting 45 items (450 MB)'}


def text_mask(text, font_path, W, H):
    """Greyscale antialiased coverage (H, W) of the header text.

    Drawn directly at the output size, so the font's hinting applies, with Pillow's BASIC
    layout engine, so letter widths are hinted whole pixels (as GDI). Drawing at 4x and
    reducing, or using the Raqm engine's unhinted fractional widths, makes the text 1-3 px
    wider than Windows'. Changed 8 Oct 2026: the 6 Oct strips (Raqm, 4x) were 24.7-49.8
    levels RMS from the lossless recordings in the text box; this is 18.7-20.4."""
    s = W / 400.0
    font = ImageFont.truetype(font_path, max(1, int(round(TEXT_PX * s))),
                              layout_engine=ImageFont.Layout.BASIC)
    im = Image.new('L', (W, H), 0)
    ImageDraw.Draw(im).text((int(round(TEXT_X * s)), int(round(TEXT_BASELINE * s))), text,
                            font=font, fill=255, anchor='ls')
    return np.asarray(im, np.float32) / 255


def strip_frames(frames, mask, style):
    """frames: premultiplied RGBA (n, H, W, 4) -> list of RGB images for one style."""
    st = STYLES[style]
    H, W = frames.shape[1:3]
    bg = tri_gradient(W, H, st['colors'])
    tc = np.array(st['text'], np.float32) / 255
    m = mask[..., None]
    out = []
    for f in frames:
        if st['text_over_movie']:
            img = f[..., :3] + bg * (1 - f[..., 3:4])       # movie over gradient
            img = img * (1 - m) + tc * m                    # then text
        else:
            img = bg * (1 - m) + tc * m                     # text over gradient
            img = f[..., :3] + img * (1 - f[..., 3:4])      # then movie
        out.append(Image.fromarray(to_u8(img), 'RGB'))
    return out


def export_strips(ftr_path, outdir, font, text=None, styles=('win7', 'vista'), name='copy',
                  sizes=((400, 40), (800, 80)), frame_ms=None, cache=None):
    data = open(ftr_path, 'rb').read()
    fps = Movie(data).fps
    if text is None:
        text = 'Copying 45 items (450 MB)'
    os.makedirs(outdir, exist_ok=True)
    written = []
    for W, H in sizes:
        frames = render_frames(data, W, H, cache)
        mask = text_mask(text, font, W, H)
        for style in styles:
            imgs = strip_frames(frames, mask, style)
            base = os.path.join(outdir, f'{name}_{W}x{H}_{style}_strip')
            save_apng(imgs, base + '.png', fps, disposal=0, frame_ms=frame_ms)
            save_gif(imgs, base + '.gif', frame_ms)
            written += [base + '.png', base + '.gif']
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('ftr'); ap.add_argument('outdir')
    ap.add_argument('--font', required=True, help='path to segoeui.ttf')
    ap.add_argument('--text', help='header text (default: "Copying 45 items (450 MB)")')
    ap.add_argument('--style', default='win7,vista')
    ap.add_argument('--name', default='copy')
    ap.add_argument('--sizes', default='400x40,800x80')
    ap.add_argument('--frame-ms', type=float)
    ap.add_argument('--cache')
    ap.add_argument('--model', choices=('gdiplus', 'geometric', 'legacy'), default=render.MODEL)
    a = ap.parse_args()
    render.MODEL = a.model
    sizes = [tuple(int(v) for v in s.lower().split('x')) for s in a.sizes.split(',')]
    for p in export_strips(a.ftr, a.outdir, a.font, a.text, tuple(a.style.split(',')), a.name,
                           sizes, a.frame_ms, a.cache):
        print(p)


if __name__ == '__main__':
    main()
