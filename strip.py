# SPDX-License-Identifier: AGPL-3.0-or-later
"""Composite rendered FTR frames over the progress-dialog header background.

Windows 7 UIFILE 42:  Gradient(argb(255,220,229,244), argb(255,155,192,227), argb(255,0,43,85), 3)
Mode 3 was identified from the recording as a three-colour horizontal gradient:
colour 1 at the left edge, colour 2 at the midpoint, colour 3 at the right edge,
linear in RGB (matches the recorded header to within ~2 levels per channel).
Vista's UIFILE uses the same mode with teal/green colours.
"""
import numpy as np

WIN7 = ((220, 229, 244), (155, 192, 227), (0, 43, 85))
VISTA = ((9, 74, 116), (32, 121, 140), (5, 111, 90))

def tri_gradient(W, H, colors=WIN7):
    c1, c2, c3 = (np.array(c, float) / 255 for c in colors)
    t = (np.arange(W) + 0.5) / W
    row = np.where(t[:, None] < 0.5, c1 + (c2 - c1) * (t[:, None] / 0.5),
                   c2 + (c3 - c2) * ((t[:, None] - 0.5) / 0.5))
    return np.broadcast_to(row, (H, W, 3)).copy()

def composite(frame_pm, colors=WIN7, header_w=None, movie_x=0):
    """frame_pm: premultiplied RGBA float (H, W, 4) -> RGB float over the header gradient."""
    H, W = frame_pm.shape[:2]
    header_w = header_w or W
    bg = tri_gradient(header_w, H, colors)
    out = bg.copy()
    x0, x1 = movie_x, min(header_w, movie_x + W)
    f = frame_pm[:, :x1 - x0]
    out[:, x0:x1] = f[..., :3] + bg[:, x0:x1] * (1 - f[..., 3:4])
    return out

def to_image(rgb):
    from PIL import Image
    return Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
