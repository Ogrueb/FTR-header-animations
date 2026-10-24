# SPDX-License-Identifier: AGPL-3.0-or-later
"""Software renderer for FTR shapes, reproducing what GDI+ draws for the calls DUI70 makes.
Matrices are GDI+ order (m11, m12, m21, m22, dx, dy):
    x' = m11*x + m21*y + dx ;  y' = m12*x + m22*y + dy

Two models (module setting MODEL):

  'gdiplus' (default, 8 Oct 2026) - GDI+'s own rasterisation, measured by replaying the decoded
      draw lists through GDI+ 1.1 on Windows 7 (gdip_replay) and on synthetic calibration draws:
      * fills: 8 x 4 samples per pixel at (i/8, j/4) from the pixel corner (not centred),
        left/top edges inclusive, right/bottom exclusive, even-odd; curves flattened to 0.25 px
      * pens up to 1.5 px wide (every FTR pen) are GDI+ "nominal" one-pixel lines: one pixel of
        ink per step along the major axis (a parallelogram 1 px thick along the minor axis),
        each segment extended 0.25 px at both ends, sampled like a fill; wider pens are widened
        polylines with miter joins (limit 10) and round caps
      * path gradients are centred on the mean of the ellipse path's 13 points, (R/13, 0) in
        brush space, shade along the ray from that centre to the ellipse, hard ellipse edge
      * the colour-transform alpha multiplies each colour's 0-255 alpha and is truncated
      Within 0.5-0.8 RMS (0-255) of GDI+ itself on all six animations.
  'geometric' - draws the geometry as the file describes it: the renderer validated on 6 Oct 2026
      (4 x 4 centred samples, curves flattened to ~1.5 px, distance-based round pens at least 1 px
      wide, radial gradients centred on the ellipse, exact float alpha). 'legacy' is accepted as
      an alias.

  Differences at a glance (geometric -> gdiplus):
      antialiasing      4 x 4 centred samples        -> 8 x 4 corner-aligned (+1/16, +1/8 px bias)
      curves            ~1.5 px segments             -> ~0.25 px segments
      pens <= 1.5 px    round stroke, >= 1 px wide   -> one-pixel nominal line, ends +0.25 px
      pens > 1.5 px     round stroke                 -> widened outline, miter joins, round caps
      radial gradients  centred on the ellipse       -> centre at (R/13, 0), GDI+'s 13-point mean
      alpha multiplier  exact fraction               -> applied to 0-255 alpha and truncated

Coordinates handed to these functions already include the +0.5 px pixel-grid offset that
timeline.Movie applies (GDI+ puts pixel centres on integer coordinates).
"""
import numpy as np

MODEL = 'gdiplus'
MODELS = ('gdiplus', 'geometric')

def model():
    """The active model name, with 'legacy' read as 'geometric'."""
    return 'geometric' if MODEL in ('geometric', 'legacy') else 'gdiplus'

def mat_mul(a, b):
    """Return matrix applying a first, then b (GDI+ row-vector convention)."""
    a11, a12, a21, a22, ax, ay = a
    b11, b12, b21, b22, bx, by = b
    return (a11*b11 + a12*b21, a11*b12 + a12*b22,
            a21*b11 + a22*b21, a21*b12 + a22*b22,
            ax*b11 + ay*b21 + bx, ax*b12 + ay*b22 + by)

def mat_inv(m):
    m11, m12, m21, m22, dx, dy = m
    det = m11*m22 - m12*m21
    if abs(det) < 1e-12:
        return None
    i11, i12, i21, i22 = m22/det, -m12/det, -m21/det, m11/det
    return (i11, i12, i21, i22, -(dx*i11 + dy*i21), -(dx*i12 + dy*i22))

def apply(m, x, y):
    return m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5]

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# ---------------------------------------------------------------- geometry
FLATTEN_STEP = {'gdiplus': 0.25, 'geometric': 1.5}     # target device px per Bezier segment
FLATTEN_MAX = {'gdiplus': 512, 'geometric': 64}

def flatten(points, m):
    """GDI+ path (x, y, type) -> list of polygons/polylines in device space."""
    step, nmax = FLATTEN_STEP[model()], FLATTEN_MAX[model()]
    polys, cur = [], []
    i = 0
    while i < len(points):
        x, y, t = points[i]
        kind = t & 0x07
        if kind == 0:
            if len(cur) > 1:
                polys.append(cur)
            cur = [apply(m, x, y)]
            i += 1
        elif kind == 1:
            cur.append(apply(m, x, y))
            i += 1
        elif kind == 3:
            p0 = cur[-1]
            p1 = apply(m, *points[i][:2])
            p2 = apply(m, *points[i+1][:2])
            p3 = apply(m, *points[i+2][:2])
            length = (np.hypot(p1[0]-p0[0], p1[1]-p0[1]) + np.hypot(p2[0]-p1[0], p2[1]-p1[1])
                      + np.hypot(p3[0]-p2[0], p3[1]-p2[1]))
            n = int(min(nmax, max(4, length / step)))
            for k in range(1, n + 1):
                s = k / n; u = 1 - s
                cur.append((u**3*p0[0] + 3*u*u*s*p1[0] + 3*u*s*s*p2[0] + s**3*p3[0],
                            u**3*p0[1] + 3*u*u*s*p1[1] + 3*u*s*s*p2[1] + s**3*p3[1]))
            i += 3
        else:
            raise ValueError(f'point type {t}')
    if len(cur) > 1:
        polys.append(cur)
    return polys

# GDI+ antialiasing grid: 8 samples across, 4 down, at (i/8, j/4) from the pixel corner.
AA_NX, AA_NY = 8, 4

def _edges(polys):
    edges = []
    for poly in polys:
        p = np.array(list(poly) + [poly[0]], dtype=np.float64)
        edges.append(np.hstack([p[:-1], p[1:]]))
    if not edges:
        return None
    e = np.vstack(edges)
    e = e[e[:, 1] != e[:, 3]]
    return e if len(e) else None

def _sample_mask(polys, W, H, nx, ny, centred):
    """Boolean sample grid (H*ny, W*nx) of the even-odd union of polys. Samples sit at
    (k + (i+0.5)/n) when centred, else at (k + i/n); a sample on a left/top edge is inside."""
    m = np.zeros((H * ny, W * nx), dtype=bool)
    e = _edges(polys)
    if e is None:
        return m
    off = 0.5 if centred else 0.0
    ymin = np.minimum(e[:, 1], e[:, 3]); ymax = np.maximum(e[:, 1], e[:, 3])
    r0 = max(0, int(np.floor(ymin.min() * ny)) - 1); r1 = min(H * ny, int(np.ceil(ymax.max() * ny)) + 1)
    c0 = max(0, int(np.floor(min(e[:, 0].min(), e[:, 2].min()) * nx)) - 1)
    c1 = min(W * nx, int(np.ceil(max(e[:, 0].max(), e[:, 2].max()) * nx)) + 2)
    if c1 <= c0 or r1 <= r0:
        return m
    sx = (np.arange(c0, c1) + off) / nx
    for row in range(r0, r1):
        y = (row + off) / ny
        sel = (ymin <= y) & (ymax > y)
        if not sel.any():
            continue
        es = e[sel]
        xs = es[:, 0] + (y - es[:, 1]) * (es[:, 2] - es[:, 0]) / (es[:, 3] - es[:, 1])
        if centred:
            m[row, c0:c1] = ((sx[:, None] > xs[None, :]).sum(axis=1) & 1).astype(bool)
        else:
            m[row, c0:c1] = ((sx[:, None] >= xs[None, :]).sum(axis=1) & 1).astype(bool)
    return m

def fill_coverage(polys, W, H, ss=4):
    """Even-odd (FillModeAlternate) antialiased coverage. ss=1: point-sampled at pixel centres
    (used for clip masks, which GDI+ does not antialias)."""
    if ss == 1:
        return _sample_mask(polys, W, H, 1, 1, True).astype(np.float64)
    if model() == 'geometric':
        return _sample_mask(polys, W, H, ss, ss, True).reshape(H, ss, W, ss).mean(axis=(1, 3))
    return _sample_mask(polys, W, H, AA_NX, AA_NY, False).reshape(H, AA_NY, W, AA_NX).mean(axis=(1, 3))

# ---------------------------------------------------------------- pens
NOMINAL_MAX_WIDTH = 1.5     # pens up to this device width are drawn as one-pixel nominal lines
NOMINAL_EXTEND = 0.25       # each nominal segment extends this far past its end points
MITER_LIMIT = 10.0

def _nominal_line(polys, W, H):
    m = np.zeros((H * AA_NY, W * AA_NX), dtype=bool)
    e = NOMINAL_EXTEND
    for poly in polys:
        for (x0, y0), (x1, y1) in zip(poly[:-1], poly[1:]):
            dx, dy = x1 - x0, y1 - y0
            if dx == 0 and dy == 0:
                continue
            if abs(dx) >= abs(dy):          # x-major: 1 px tall
                s = np.sign(dx); k = dy / dx
                xa, xb = x0 - s * e, x1 + s * e
                ya, yb = y0 - s * e * k, y1 + s * e * k
                quad = [(xa, ya - .5), (xb, yb - .5), (xb, yb + .5), (xa, ya + .5)]
            else:                           # y-major: 1 px wide
                s = np.sign(dy); k = dx / dy
                ya, yb = y0 - s * e, y1 + s * e
                xa, xb = x0 - s * e * k, x1 + s * e * k
                quad = [(xa - .5, ya), (xb - .5, yb), (xb + .5, yb), (xa + .5, ya)]
            m |= _sample_mask([quad], W, H, AA_NX, AA_NY, False)
    return m.reshape(H, AA_NY, W, AA_NX).mean(axis=(1, 3))

def _wide_pen(polys, width, W, H):
    """Widened polyline: segment quads, miter joins (bevel past the limit) and round caps."""
    r = width / 2.0
    m = np.zeros((H * AA_NY, W * AA_NX), dtype=bool)
    circle = [(r * np.cos(a), r * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 33)[:-1]]
    add = lambda poly: _sample_mask([poly], W, H, AA_NX, AA_NY, False)
    for poly in polys:
        pts = [np.array(poly[0], float)]
        for p in poly[1:]:
            p = np.array(p, float)
            if np.hypot(*(p - pts[-1])) > 1e-9:
                pts.append(p)
        if len(pts) == 1:
            m |= add([(pts[0][0] + x, pts[0][1] + y) for x, y in circle])
            continue
        normals = []
        for a, b in zip(pts[:-1], pts[1:]):
            d = (b - a) / np.hypot(*(b - a)); n = np.array([-d[1], d[0]]) * r
            normals.append(n)
            m |= add([tuple(a + n), tuple(b + n), tuple(b - n), tuple(a - n)])
        for i in range(1, len(pts) - 1):
            v = pts[i]; d1 = pts[i] - pts[i - 1]; d2 = pts[i + 1] - pts[i]
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) < 1e-12:
                continue
            for s in (1, -1):
                a1, a2 = v + s * normals[i - 1], v + s * normals[i]
                t = ((a2 - a1)[0] * d2[1] - (a2 - a1)[1] * d2[0]) / den
                tip = a1 + t * d1
                if np.hypot(*(tip - v)) <= MITER_LIMIT * r:
                    m |= add([tuple(v), tuple(a1), tuple(tip), tuple(a2)])
                else:
                    m |= add([tuple(v), tuple(a1), tuple(a2)])
        for c in (pts[0], pts[-1]):
            m |= add([(c[0] + x, c[1] + y) for x, y in circle])
    return m.reshape(H, AA_NY, W, AA_NX).mean(axis=(1, 3))

def _geometric_stroke(polys, width, W, H, ss=4):
    """Round-capped stroke, distance-based, 4x4 centred samples (6 Oct 2026 renderer)."""
    r = max(width / 2, 0.5 / ss)
    cov = np.zeros((H * ss, W * ss), dtype=bool)
    yy, xx = np.mgrid[0:H*ss, 0:W*ss]
    px = (xx + 0.5) / ss; py = (yy + 0.5) / ss
    for poly in polys:
        for (x0, y0), (x1, y1) in zip(poly[:-1], poly[1:]):
            dx, dy = x1 - x0, y1 - y0
            L2 = dx*dx + dy*dy
            t = np.clip(((px - x0)*dx + (py - y0)*dy) / L2, 0, 1) if L2 > 0 else 0
            cov |= (px - (x0 + t*dx))**2 + (py - (y0 + t*dy))**2 <= r*r
    return cov.reshape(H, ss, W, ss).mean(axis=(1, 3))

def stroke_coverage(polys, width, W, H, ss=4):
    """Coverage of a GDI+ pen (round caps) of the given device width along open polylines."""
    if model() == 'geometric':
        return _geometric_stroke(polys, max(width, MIN_PEN_WIDTH), W, H, ss)
    if width <= NOMINAL_MAX_WIDTH:
        return _nominal_line(polys, W, H)
    return _wide_pen(polys, width, W, H)

# ---------------------------------------------------------------- paint
# GDI+ interpolates gradient stops in premultiplied ARGB (confirmed against the Win7 recording)
PREMULTIPLIED_BLEND = {'linear': True, 'radial': True}
RADIAL_CENTRE_X = 1.0 / 13.0    # GDI+ path-gradient centre: mean of the 13 ellipse path points

def _blend(stops, t, premultiplied=False):
    """Interpolate preset-blend stops (color RGBA 0-255, position) at t (array)."""
    pos = np.array([p for _, p in stops]); cols = np.array([c for c, _ in stops], dtype=np.float64) / 255.0
    order = np.argsort(pos, kind='stable'); pos = pos[order]; cols = cols[order]
    if premultiplied:
        cols = cols.copy(); cols[:, :3] *= cols[:, 3:4]
    out = np.empty(t.shape + (4,))
    for ch in range(4):
        out[..., ch] = np.interp(t, pos, cols[:, ch])
    if premultiplied:
        a = out[..., 3:4]
        out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0)
    return out

def paint(fill, to_device, W, H):
    """Straight-alpha RGBA (float 0-1) for a fill; alpha 0 where the brush paints nothing."""
    if fill['kind'] == 'solid':
        c = np.array(fill['color'], dtype=np.float64) / 255.0
        return np.broadcast_to(c, (H, W, 4)).copy()
    gm = mat_mul(fill['matrix'], to_device)          # gradient space -> device
    inv = mat_inv(gm)
    if inv is None:
        return np.zeros((H, W, 4))
    yy, xx = np.mgrid[0:H, 0:W]
    gx, gy = apply(inv, xx + 0.5, yy + 0.5)
    if fill['kind'] == 'gradient4':                   # GdipCreateLineBrush (-16384,0)->(16384,0), WrapModeTileFlipXY
        t = (gx + 16384.0) / 32768.0
        t = np.abs(((t % 2.0) + 2.0) % 2.0)
        t = np.where(t > 1.0, 2.0 - t, t)
        return _blend(fill['stops'], t, PREMULTIPLIED_BLEND['linear'])
    if fill['kind'] == 'gradient3':                   # path gradient on ellipse radius 16384; 0 = edge, 1 = centre
        px, py = gx / 16384.0, gy / 16384.0
        if model() == 'geometric':
            d = np.hypot(px, py)
        else:                                         # fraction of the ray from the centre (cx, 0) to the ellipse
            cx = RADIAL_CENTRE_X
            dx = px - cx; a = dx*dx + py*py; b = 2*cx*dx; c = cx*cx - 1
            t = (-b + np.sqrt(np.maximum(b*b - 4*a*c, 0))) / (2*np.maximum(a, 1e-18))
            d = np.where(a > 1e-18, 1.0 / np.maximum(t, 1e-18), 0.0)
        rgba = _blend(fill['stops'], 1.0 - np.clip(d, 0, 1), PREMULTIPLIED_BLEND['radial'])
        rgba[..., 3] *= (px*px + py*py) <= 1.0        # nothing outside the ellipse (hard edge)
        return rgba
    raise ValueError(fill['kind'])

def over(dst, rgba, cov):
    """Composite straight-alpha rgba with coverage onto premultiplied dst (in place)."""
    a = rgba[..., 3] * cov
    dst[..., :3] = rgba[..., :3] * a[..., None] + dst[..., :3] * (1 - a[..., None])
    dst[..., 3] = a + dst[..., 3] * (1 - a)

# Geometric model only: the 6 Oct renderer's minimum pen width (the gdiplus model draws every pen up to
# NOMINAL_MAX_WIDTH as a one-pixel nominal line instead).
MIN_PEN_WIDTH = 1.0

def _alpha_mul(color, mul):
    """The player multiplies a colour's 0-255 alpha by the colour-transform multiplier, truncating."""
    if mul >= 1.0:
        return tuple(color)
    return tuple(color[:3]) + (int(color[3] * mul),)

def draw_shape(dst, shape, to_device, cxform=None):
    """Draw a DefineShape onto premultiplied RGBA float dst using its draw list."""
    H, W = dst.shape[:2]
    mul = 1.0 if cxform is None else cxform[3][0]
    gdip = model() == 'gdiplus'
    fill_i, line_i = -1, -1
    for op, arg in shape['draws']:
        if op == 1:
            fill_i = arg
        elif op == 0:
            line_i = arg
        elif op == 2:
            polys = flatten(shape['paths'][arg], to_device)
            if 0 <= fill_i < len(shape['fills']):
                f = shape['fills'][fill_i]
                if gdip and mul < 1.0:
                    f = dict(f)
                    if f['kind'] == 'solid':
                        f['color'] = _alpha_mul(f['color'], mul)
                    else:
                        f['stops'] = [(_alpha_mul(c, mul), p) for c, p in f['stops']]
                rgba = paint(f, to_device, W, H)
                if not gdip and cxform is not None:
                    rgba = apply_cxform(rgba, cxform)
                over(dst, rgba, fill_coverage(polys, W, H))
            if 0 <= line_i < len(shape['lines']):
                (color, width) = shape['lines'][line_i]
                scale = np.sqrt(abs(to_device[0]*to_device[3] - to_device[1]*to_device[2]))
                if gdip:
                    color = _alpha_mul(color, mul)
                rgba = np.broadcast_to(np.array(color, float) / 255.0, (H, W, 4)).copy()
                if not gdip and cxform is not None:
                    rgba = apply_cxform(rgba, cxform)
                over(dst, rgba, stroke_coverage(polys, width * scale, W, H))

def apply_cxform(rgba, cx):
    """cx = [(mult, add)] for R,G,B,A applied as a GDI+ ColorMatrix (adds in 0-1 units)."""
    out = rgba.copy()
    for ch, (mul, add) in enumerate(cx):
        out[..., ch] = np.clip(rgba[..., ch] * mul + add, 0, 1)
    return out
