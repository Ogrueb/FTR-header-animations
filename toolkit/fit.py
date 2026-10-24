# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fit a rendered FTR animation to a recorded header strip and score it (recreated 5 Oct 2026).

Replaces fit6.py, which only scored placement values given to it. This script:
  1. fits the header gradient's position and width from the recording itself
     (per-column median over time, right of the text);
  2. searches the movie placement: scale k (recording px per guest px) and offset x0, y0;
  3. matches every recorded frame to its best rendered frame and reports RMS error
     (median, 90th percentile, maximum) and whether the matched sequence advances
     monotonically, wrapping at the loop point;
  4. writes per-frame results (CSV), a summary (JSON) and amplified difference images
     of the worst frames.

Usage:
  python fit.py FTR REC.npz OUTDIR [--bg win7|vista] [--text-until 430]
                [--scale K [--fix-scale]] [--render-scale R] [--cache DIR] [--skip-left 12]

REC.npz comes from crop.py. Only columns at or right of --text-until (crop pixels) are
compared, to keep the header text out; set it to 0 for a recording without text over the
movie. --scale gives a starting guess for k; by default it is taken from the gradient fit.
When the VM's display scale is known, pass it with --fix-scale (k = host px per guest px;
the 2026-09-29 Win7 recording is 1.75: a 1024x768 guest shown as 1792x1344).
Frames are rendered once at R guest-pixel multiples (default: k rounded up, minimum 2) and
cached with --cache. Needs NumPy, SciPy and Pillow.
"""
import argparse
import csv
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates
from scipy.optimize import least_squares, minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compose import WIN7, VISTA      # noqa: E402
from export import render_frames     # noqa: E402

GUEST_W, GUEST_H = 400, 40


def gradient_row(W, GL, GW, colors):
    c1, c2, c3 = (np.array(c, float) / 255 for c in colors)
    t = np.clip((np.arange(W) + 0.5 - GL) / GW, 0, 1)[:, None]
    return np.where(t < 0.5, c1 + (c2 - c1) * t / 0.5, c2 + (c3 - c2) * (t - 0.5) / 0.5)


def fit_gradient(rec, xs, colors, skip_left=12, edge=0.15):
    """Header gradient start and width (crop px) from the per-column temporal median.

    Uses the top and bottom rows (the header text sits between them) left of xs, where the
    animation rarely draws, so the fit sees the left half of the gradient and its midpoint.
    The first skip_left columns are left out (window border). A robust loss limits the pull
    of anything the median does not remove. With no text (xs == 0) every row and column is
    used instead.

    A per-channel colour offset is fitted too: captures shift colours by a few levels
    (about -2/255 in the 2026-09-29 recording), and without the offset the fit moves the
    gradient's edges to compensate. The same offset is applied to every rendered frame."""
    H, W = rec.shape[1:3]
    med = np.median(rec, axis=0)                       # (H, W, 3)
    if xs > 0:
        e = max(1, int(H * edge))
        col = np.concatenate([med[:e], med[-e:]]).mean(axis=0)
        lo, hi = skip_left, xs
    else:
        col, lo, hi = med.mean(axis=0), skip_left, W

    def resid(p):
        return (gradient_row(W, p[0], p[1], colors)[lo:hi] + p[2:5] - col[lo:hi]).ravel()
    best = None
    for gw in (W * 0.75, W, W * 1.25):                 # a few starts; the clip makes it non-convex
        r = least_squares(resid, [0.0, gw, 0, 0, 0], loss='soft_l1', f_scale=0.02)
        if best is None or r.cost < best.cost:
            best = r
    return float(best.x[0]), float(best.x[1]), best.x[2:5].copy()


class Matcher:
    def __init__(self, frames, R, rec, xs, bg_row, offset=0.0):
        self.frames, self.R, self.xs = frames, R, xs
        self.rec = rec[:, :, xs:]
        H, W = rec.shape[1:3]
        self.bg = np.broadcast_to(bg_row[xs:], (H, W - xs, 3))
        self.yy, self.xx = np.mgrid[0:H, xs:W].astype(float)
        self.offset = np.asarray(offset, np.float32)

    def warp(self, k, x0, y0, idx=None):
        gx = (self.xx + 0.5 - x0) / k
        gy = (self.yy + 0.5 - y0) / k
        sx, sy = gx * self.R - 0.5, gy * self.R - 0.5
        inside = ((gx >= 0) & (gx < GUEST_W) & (gy >= 0) & (gy < GUEST_H))[..., None]
        out = []
        for f in (self.frames if idx is None else self.frames[idx]):
            pm = np.stack([map_coordinates(f[..., c], [sy, sx], order=1, mode='constant')
                           for c in range(4)], -1) * inside
            out.append(pm[..., :3] + self.bg * (1 - pm[..., 3:4]) + self.offset)
        return np.array(out, np.float32)

    def mse(self, k, x0, y0, rec_idx=None, render_idx=None):
        """(n_rec, n_render) mean squared error matrix."""
        ws = self.warp(k, x0, y0, render_idx)
        R = self.rec if rec_idx is None else self.rec[rec_idx]
        return np.stack([((r[None] - ws) ** 2).mean(axis=(1, 2, 3)) for r in R])


def sequence_report(match, n):
    steps = np.diff(match) % n
    return {'repeats': int((steps == 0).sum()), 'advance_1_to_3': int(((steps >= 1) & (steps <= 3)).sum()),
            'jumps': int((steps > 3).sum()), 'wraps': int((np.diff(match) < 0).sum())}


def run(ftr, rec_path, outdir, bg='win7', xs=430, scale=None, R=None, cache=None, skip_left=12,
        fix_scale=False):
    colors = {'win7': WIN7, 'vista': VISTA}[bg]
    z = np.load(rec_path)
    rec = z['frames'].astype(np.float32) / 255
    N, H, W = rec.shape[:3]
    os.makedirs(outdir, exist_ok=True)

    GL, GW, off = fit_gradient(rec, xs, colors, skip_left)
    k0 = scale or GW / GUEST_W
    print(f'gradient: start {GL:.2f}, width {GW:.2f} px, colour offset {np.round(off * 255, 2)}'
          f'  ->  initial k {k0:.3f}')

    R = R or max(2, math.ceil(k0))
    data = open(ftr, 'rb').read()
    frames = render_frames(data, GUEST_W * R, GUEST_H * R, cache)
    n = len(frames)
    m = Matcher(frames, R, rec, xs, gradient_row(W, GL, GW, colors), off)

    # placement search on a spread of frames; trimmed mean ignores frames without the dialog
    sub = np.linspace(0, N - 1, min(N, 24)).round().astype(int)

    start = np.array([k0, GL, (H - GUEST_H * k0) / 2])
    # candidate rendered frames per sampled recorded frame, found once at the starting placement
    D0 = m.mse(*start, rec_idx=sub)
    cand = np.unique(np.argsort(D0, axis=1)[:, :3])

    def objective(p):
        e = np.sort(m.mse(*p, rec_idx=sub, render_idx=cand).min(1))
        return e[: max(1, int(len(e) * 0.8))].mean()
    if fix_scale:                                       # k known (e.g. from the VM's scale setting)
        best = minimize(lambda q: objective([k0, q[0], q[1]]), start[1:], method='Nelder-Mead',
                        options={'xatol': 0.01, 'fatol': 1e-9, 'maxiter': 200,
                                 'initial_simplex': [start[1:] + d for d in ([0, 0], [1.5, 0], [0, 1.5])]})
        k, (x0, y0) = k0, best.x
    else:
        best = minimize(objective, start, method='Nelder-Mead',
                        options={'xatol': 0.01, 'fatol': 1e-9, 'maxiter': 300,
                                 'initial_simplex': [start + d for d in
                                                     ([0, 0, 0], [0.05, 0, 0], [0, 1.5, 0], [0, 0, 1.5])]})
        k, x0, y0 = best.x
    print(f'placement: k {k:.4f}, x0 {x0:.3f}, y0 {y0:.3f}')

    D = m.mse(k, x0, y0)
    match, rms = D.argmin(1), np.sqrt(D.min(1)) * 255
    valid = rms < max(20.0, 3 * np.median(rms))         # drops frames before/after the dialog
    seq = sequence_report(match[valid], n)
    summary = {'ftr': os.path.basename(ftr), 'recording': os.path.basename(rec_path), 'background': bg,
               'compare_from_x': xs, 'render_scale': R, 'gradient_start': GL, 'gradient_width': GW,
               'colour_offset_255': [round(float(v) * 255, 2) for v in off],
               'k': k, 'k_fixed': bool(fix_scale), 'x0': x0, 'y0': y0, 'distinct_frames': int(N), 'valid_frames': int(valid.sum()),
               'rms_median': float(np.median(rms[valid])), 'rms_p90': float(np.percentile(rms[valid], 90)),
               'rms_max': float(rms[valid].max()), 'movie_frames_seen': int(len(set(match[valid]))),
               'movie_frames': int(n), 'sequence': seq}
    print(json.dumps(summary, indent=1))
    json.dump(summary, open(os.path.join(outdir, 'summary.json'), 'w'), indent=1)

    with open(os.path.join(outdir, 'frames.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['distinct_frame', 'recording_frame', 'movie_frame', 'rms', 'valid'])
        for i in range(N):
            wr.writerow([i, int(z['src_index'][i]), int(match[i]) + 1, f'{rms[i]:.2f}', int(valid[i])])

    # worst valid frames: recording / render / difference x4 around mid-grey
    worst = np.argsort(np.where(valid, rms, -1))[::-1][:5]
    for rank, i in enumerate(worst):
        r = m.rec[i]
        w = m.warp(k, x0, y0, idx=[match[i]])[0]
        img = np.vstack([r, w, np.clip(0.5 + 4 * (r - w), 0, 1)])
        Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize(
            (img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(
            os.path.join(outdir, f'worst{rank + 1}_rec{i}_movie{match[i] + 1}.png'))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('ftr')
    ap.add_argument('rec', help='.npz from crop.py')
    ap.add_argument('outdir')
    ap.add_argument('--bg', choices=('win7', 'vista'), default='win7')
    ap.add_argument('--text-until', type=int, default=430, help='first crop column compared')
    ap.add_argument('--scale', type=float, help='starting guess for k')
    ap.add_argument('--fix-scale', action='store_true', help='hold k at --scale; fit only x0, y0')
    ap.add_argument('--render-scale', type=int, help='render at this many px per guest px')
    ap.add_argument('--cache', help='directory for rendered .npy frames')
    ap.add_argument('--skip-left', type=int, default=12,
                    help='crop columns at the left edge left out of the gradient fit (window border)')
    a = ap.parse_args()
    if a.fix_scale and not a.scale:
        ap.error('--fix-scale needs --scale')
    run(a.ftr, a.rec, a.outdir, a.bg, a.text_until, a.scale, a.render_scale, a.cache, a.skip_left,
        a.fix_scale)


if __name__ == '__main__':
    main()
