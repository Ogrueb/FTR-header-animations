# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crop the progress-dialog header strip from a screen recording (recreated 5 Oct 2026).

Decodes the recording with ffmpeg, keeps the header rectangle, drops repeated frames
(the capture usually runs faster than the animation), and saves an .npz with:
  frames     uint8 (N, h, w, 3)  distinct header strips, in recording order
  src_index  int   (N,)          frame number of each strip in the recording
  src_fps    float               the recording's frame rate
  rect       int   (4,)          x, y, w, h of the crop in recording pixels

Usage:
  python crop.py RECORDING --preview frame.png [--at SECONDS]
      save one full frame, to read the header rectangle from
  python crop.py RECORDING OUT.npz --rect X,Y,W,H [--threshold 0.5]

For the 2026-09-29 Win7 copy recording the rectangle was 556,576,710,68.
Make the rectangle cover the whole header height and run past both ends of the movie
if possible; fit.py finds the exact placement. Needs ffmpeg and ffprobe on PATH.
"""
import argparse
import json
import subprocess
import sys

import numpy as np


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,r_frame_rate', '-of', 'json', path],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    num, den = s['r_frame_rate'].split('/')
    return int(s['width']), int(s['height']), float(num) / float(den)


def preview(path, png, at=1.0):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(at), '-i', path, '-frames:v', '1', png],
                   check=True)


def crop(path, out, rect, threshold=0.5):
    x, y, w, h = rect
    _, _, fps = probe(path)
    cmd = ['ffmpeg', '-v', 'error', '-i', path, '-vf', f'crop={w}:{h}:{x}:{y}',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * 3
    frames, idx, prev, n = [], [], None, 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        if prev is None or np.abs(f.astype(np.int16) - prev).mean() > threshold:
            frames.append(f.copy())
            idx.append(n)
        prev = f.astype(np.int16)
        n += 1
    proc.wait()
    if proc.returncode:
        sys.exit(f'ffmpeg failed ({proc.returncode})')
    np.savez_compressed(out, frames=np.array(frames), src_index=np.array(idx), src_fps=fps,
                        rect=np.array(rect))
    print(f'{n} recorded frames, {len(frames)} distinct, at {fps:g} fps -> {out}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('recording')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--rect', help='X,Y,W,H of the header strip in recording pixels')
    ap.add_argument('--threshold', type=float, default=0.5,
                    help='mean absolute change (0-255) that counts as a new frame')
    ap.add_argument('--preview', help='save one full frame to this PNG and exit')
    ap.add_argument('--at', type=float, default=1.0, help='time of the preview frame, seconds')
    a = ap.parse_args()
    if a.preview:
        preview(a.recording, a.preview, a.at)
        return
    if not (a.out and a.rect):
        ap.error('OUT and --rect are required unless --preview is given')
    crop(a.recording, a.out, tuple(int(v) for v in a.rect.split(',')), a.threshold)


if __name__ == '__main__':
    main()
