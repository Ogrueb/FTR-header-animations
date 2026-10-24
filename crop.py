# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export an FTR animation as PNG sequences, APNGs and GIFs (recreated 5 Oct 2026).

Reproduces the original copy-animation exports pixel for pixel when run with the
pre-fix renderer, so its output conventions match the files already published:

  <name>_<W>x<H>_transparent_png/<name>_NN.png   straight (non-premultiplied) RGBA, one per frame
  <name>_<W>x<H>_transparent.png                  APNG, RGBA, disposal 1 (background), blend 0
  <name>_<W>x<H>_win7.png / _vista.png            APNG, RGB, composited over the header gradient
  <name>_<W>x<H>_win7.gif / _vista.gif            GIF, 256 colours, 40 ms frames (quick viewing only)

APNG frames last exactly 1000/fps ms and loop forever. Frame NN is the movie's frame NN+1.

Usage:
  python export.py ftr_201_copy.bin OUTDIR [--name copy] [--sizes 400x40,800x80]
                   [--cache DIR] [--only seq,apng,composite,gif] [--frame-ms MS]
                   [--model gdiplus|geometric]

--model picks the rasterisation model in render.py: gdiplus (default since 8 Oct 2026, GDI+'s
own antialiasing, nominal one-pixel pens and path-gradient centring) or geometric (the
geometry as the file describes it; the renderer the 6 Oct 2026 exports were made with).
'legacy' is accepted as an alias for geometric.

--frame-ms sets the frame time instead of the declared 1000/fps. 46.875 gives the speed
Windows actually plays at (a 41 ms timer rounded up to the default 15.625 ms tick, i.e.
21.33 fps). APNG stores the exact value; GIF can only store whole hundredths of a second,
so its frame times alternate (e.g. 40/50 ms) to keep the exact average. Without
--frame-ms, GIFs use a constant 40 ms as the original exports did.

--cache stores the rendered premultiplied frames as .npy, so a rerun (or a run split
across several shell calls) does not render again. Rendering costs roughly 0.4 s per
frame at 400x40 and 1.5 s at 800x80.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render                                   # noqa: E402
from timeline import Movie                      # noqa: E402
from compose import composite, WIN7, VISTA      # noqa: E402


def render_frames(data, W, H, cache=None):
    """All frames of one loop as premultiplied RGBA float32, shape (n, H, W, 4)."""
    path = None
    if cache:
        os.makedirs(cache, exist_ok=True)
        import hashlib
        key = hashlib.md5(data).hexdigest()[:12]
        tag = '' if render.model() == 'geometric' else f'_{render.model()}'   # geometric keeps the old cache names
        path = os.path.join(cache, f'frames_{key}{tag}_{W}x{H}.npy')
        if os.path.exists(path):
            return np.load(path)
    mv = Movie(data)
    n = len(mv.root.tl['frames'])
    out = np.empty((n, H, W, 4), np.float32)
    for k in range(n):
        mv.root.advance()
        out[k] = mv.root.render(W, H)
        print(f'  rendered {W}x{H} frame {k + 1}/{n}', file=sys.stderr)
    if path:
        np.save(path, out)
    return out


def to_u8(x):
    return (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)


def straight_rgba(pm):
    """Premultiplied RGBA float -> straight RGBA uint8 (colour 0 where alpha is 0)."""
    a = pm[..., 3:4]
    rgb = np.where(a > 1e-6, pm[..., :3] / np.maximum(a, 1e-6), 0)
    return to_u8(np.concatenate([rgb, a], -1))


def save_apng(images, path, fps, disposal, frame_ms=None):
    images[0].save(path, format='PNG', save_all=True, append_images=images[1:],
                   duration=frame_ms or 1000 / fps, loop=0, disposal=disposal, blend=0)


def gif_durations(n, frame_ms=None):
    """Constant 40 ms (original convention), or whole-10-ms steps averaging frame_ms exactly."""
    if not frame_ms:
        return 40
    edges = [int(round(k * frame_ms / 10.0)) * 10 for k in range(n + 1)]
    return [b - a for a, b in zip(edges[:-1], edges[1:])]


def save_gif(images, path, frame_ms=None):
    images[0].save(path, format='GIF', save_all=True, append_images=images[1:],
                   duration=gif_durations(len(images), frame_ms), loop=0)


def export(ftr_path, outdir, name='copy', sizes=((400, 40), (800, 80)), cache=None,
           only=('seq', 'apng', 'composite', 'gif'), frame_ms=None):
    data = open(ftr_path, 'rb').read()
    fps = Movie(data).fps
    os.makedirs(outdir, exist_ok=True)
    written = []
    for W, H in sizes:
        frames = render_frames(data, W, H, cache)
        base = os.path.join(outdir, f'{name}_{W}x{H}')
        rgba = [Image.fromarray(straight_rgba(f), 'RGBA') for f in frames]
        if 'seq' in only:
            seq_dir = base + '_transparent_png'
            os.makedirs(seq_dir, exist_ok=True)
            for k, im in enumerate(rgba):
                p = os.path.join(seq_dir, f'{name}_{k:02d}.png')
                im.save(p)
                written.append(p)
        if 'apng' in only:
            save_apng(rgba, base + '_transparent.png', fps, disposal=1, frame_ms=frame_ms)
            written.append(base + '_transparent.png')
        for label, colors in (('win7', WIN7), ('vista', VISTA)):
            comp = [Image.fromarray(to_u8(composite(f, colors)), 'RGB') for f in frames]
            if 'composite' in only:
                save_apng(comp, f'{base}_{label}.png', fps, disposal=0, frame_ms=frame_ms)
                written.append(f'{base}_{label}.png')
            if 'gif' in only:
                save_gif(comp, f'{base}_{label}.gif', frame_ms)
                written.append(f'{base}_{label}.gif')
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('ftr', help='FTR resource bytes, e.g. ftr_201_copy.bin')
    ap.add_argument('outdir')
    ap.add_argument('--name', default='copy', help='file name prefix (default: copy)')
    ap.add_argument('--sizes', default='400x40,800x80', help='comma-separated WxH list')
    ap.add_argument('--cache', help='directory for rendered .npy frames')
    ap.add_argument('--only', default='seq,apng,composite,gif',
                    help='subset of seq,apng,composite,gif')
    ap.add_argument('--frame-ms', type=float,
                    help='frame time in ms instead of 1000/fps (46.875 = real Windows speed)')
    ap.add_argument('--model', choices=('gdiplus', 'geometric', 'legacy'), default=render.MODEL,
                    help='rasterisation model (default: gdiplus; legacy = geometric)')
    a = ap.parse_args()
    render.MODEL = a.model
    sizes = [tuple(int(v) for v in s.lower().split('x')) for s in a.sizes.split(',')]
    for p in export(a.ftr, a.outdir, a.name, sizes, a.cache, tuple(a.only.split(',')), a.frame_ms):
        print(p)


if __name__ == '__main__':
    main()
