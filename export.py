# SPDX-License-Identifier: AGPL-3.0-or-later
"""Timeline / display-list engine for FTR ("Fluster") movies.

PlaceObject2 fields (confirmed against display-list consistency in all six files):
    b9  = is clip layer        w14 = clip depth (0xFFFF none)
    be  = has character        w12 = character id (0xFFFF when absent)
    bf  = move (modify object already at depth)
    w10 = depth
Matrix / colour transform persist on the object until a later move replaces them.
"""
import numpy as np
from ftr import parse
from render import draw_shape, fill_coverage, flatten, mat_mul, IDENTITY

def split_frames(records):
    frames, cur = [], []
    for r in records:
        if r['name'] == 'ShowFrame':
            frames.append(cur); cur = []
        elif r['name'] in ('PlaceObject2', 'RemoveObject2'):
            cur.append(r)
    if cur:
        frames.append(cur)
    return frames

class Movie:
    def __init__(self, data, hard_masks=True, pixel_offset=0.5):
        m = parse(data)
        self.hard_masks = hard_masks          # GDI+ clip regions are aliased (see coverage)
        # GDI+ default PixelOffsetMode puts pixel centres on integer coordinates; this renderer
        # samples at +0.5, so the movie is shifted by +0.5 px to match (DUI70 sets no offset
        # mode). Confirmed on 1:1 recordings of FTR 201-205: error roughly halves. 0 = old behaviour.
        self.pixel_offset = pixel_offset
        self.rect, self.fps = m['rect'], m['fps']
        self.chars = {}
        self._collect(m['records'])
        self.root = Instance(self, {'frames': split_frames(m['records'])})

    def _collect(self, recs):
        for r in recs:
            if r['name'].startswith('DefineShape'):
                self.chars[r['id']] = ('shape', r)
            elif r['name'] == 'DefineSprite':
                self.chars[r['id']] = ('sprite', {'frames': split_frames(r['records'])})
                self._collect(r['records'])

class Instance:
    """A running timeline (main movie or a placed sprite)."""
    def __init__(self, movie, timeline):
        self.movie, self.tl = movie, timeline
        self.frame = -1
        self.dl = {}                        # depth -> object dict

    def _make_obj(self, cid):
        kind, d = self.movie.chars[cid]
        obj = {'cid': cid, 'kind': kind, 'def': d, 'matrix': IDENTITY, 'alpha': 1.0,
               'clip': False, 'clip_depth': None, 'inst': None}
        if kind == 'sprite':
            obj['inst'] = Instance(self.movie, d)
            obj['inst'].advance()           # a newly placed sprite shows its first frame immediately
        return obj

    def _exec(self, tag):
        if tag['name'] == 'RemoveObject2':
            self.dl.pop(tag['depth'], None)
            return
        depth = tag['w10']
        if tag['be']:
            old = self.dl.get(depth)
            obj = self._make_obj(tag['w12'])
            if tag['bf'] and old is not None:           # replace: keep transforms unless given
                obj['matrix'], obj['alpha'] = old['matrix'], old['alpha']
            self.dl[depth] = obj
        obj = self.dl.get(depth)
        if obj is None:
            return
        if tag['has_matrix']:
            obj['matrix'] = tag['matrix']
        if tag['has_cxform']:
            obj['alpha'] = tag['cxform'][3][0]          # files only ever use the alpha multiplier
        if tag['b9']:
            obj['clip'], obj['clip_depth'] = True, tag['w14']

    def advance(self):
        """Step to the next frame (looping), running children first as Flash does."""
        n = len(self.tl['frames'])
        if n == 0:
            return
        for obj in list(self.dl.values()):
            if obj['inst'] is not None:
                obj['inst'].advance()
        self.frame += 1
        if self.frame >= n:                 # loop: rebuild display list from frame 0
            self.frame = 0
            self.dl = {}
        for tag in self.tl['frames'][self.frame]:
            self._exec(tag)

    # ------------------------------------------------------------ drawing
    def draw(self, dst, to_device, alpha=1.0):
        self._draw_items(dst, sorted(self.dl.items()), to_device, alpha)

    def _draw_items(self, dst, items, to_device, alpha):
        """Draw (depth, obj) pairs in depth order. A clip layer masks every depth up to and
        including its clip depth; the range under it is drawn recursively, so a mask nested
        inside another mask's range applies within it. Confirmed in DUI70 6.1: clips are kept
        on a stack; a new clip uses CombineModeIntersect when the stack is not empty, a clip is
        popped after the object at its clip depth is drawn, and the remaining clips are then
        re-applied (Replace, then Intersect) after GdipResetClip."""
        i = 0
        while i < len(items):
            depth, obj = items[i]
            if obj['clip']:
                mask = self.coverage(obj, to_device, dst.shape[1], dst.shape[0])
                j = i + 1
                while j < len(items) and items[j][0] <= obj['clip_depth']:
                    j += 1
                layer = np.zeros_like(dst)
                self._draw_items(layer, items[i + 1:j], to_device, alpha)
                layer *= mask[..., None]
                dst[...] = layer + dst * (1 - layer[..., 3:4])
                i = j
                continue
            self._draw_obj(dst, obj, to_device, alpha)
            i += 1

    def _draw_obj(self, dst, obj, to_device, alpha):
        m = mat_mul(obj['matrix'], to_device)
        a = alpha * obj['alpha']
        if a <= 0:
            return
        if obj['kind'] == 'shape':
            draw_shape(dst, obj['def'], m, cxform=None if a >= 1 else [(1, 0), (1, 0), (1, 0), (a, 0)])
        else:
            obj['inst'].draw(dst, m, a)

    def coverage(self, obj, to_device, W, H):
        """Mask of a clip character's geometry (colour ignored).

        Matches DUI70 6.1 (the clip routine at 0x7ff43d5cb70): every path the shape's draw
        list draws is appended to ONE GraphicsPath (FillModeAlternate, so even-odd across all
        of them) and passed to GdipSetClipPath. GDI+ clip regions are not antialiased, so by
        default the mask is point-sampled at pixel centres (hard edges). Set
        Movie.hard_masks = False for the earlier antialiased union of paths."""
        m = mat_mul(obj['matrix'], to_device)
        if obj['kind'] == 'shape':
            if getattr(self.movie, 'hard_masks', True):
                polys = []
                for i, path in enumerate(obj['def']['paths']):
                    if any(op == 2 and arg == i for op, arg in obj['def']['draws']):
                        polys += flatten(path, m)
                return fill_coverage(polys, W, H, ss=1)
            cov = np.zeros((H, W))
            for path in obj['def']['paths']:
                c = fill_coverage(flatten(path, m), W, H)
                cov = cov + c - cov * c
            return cov
        cov = np.zeros((H, W))
        for _, child in sorted(obj['inst'].dl.items()):
            if not child['clip']:
                c = obj['inst'].coverage(child, m, W, H)
                cov = cov + c - cov * c
        return cov

    def display_list(self, indent=0):
        lines = []
        for depth, o in sorted(self.dl.items()):
            tag = f"clip->{o['clip_depth']}" if o['clip'] else ''
            m = o['matrix']
            lines.append(f"{'  '*indent}depth {depth:3} {o['kind']:6} id {o['cid']:3} alpha {o['alpha']:.2f} "
                         f"pos ({m[4]:.0f},{m[5]:.0f}) {tag}")
            if o['inst'] is not None:
                lines.append(f"{'  '*indent}  [sprite frame {o['inst'].frame+1}/{len(o['inst'].tl['frames'])}]")
                lines += o['inst'].display_list(indent + 2)
        return lines

    def render(self, W, H):
        """Premultiplied RGBA float frame, frame rect scaled to W x H."""
        l, t, r, b = self.movie.rect
        sx, sy = W / (r - l), H / (b - t)
        dst = np.zeros((H, W, 4))
        off = getattr(self.movie, 'pixel_offset', 0.0)
        self.draw(dst, (sx, 0.0, 0.0, sy, -l * sx + off, -t * sy + off))
        return dst
