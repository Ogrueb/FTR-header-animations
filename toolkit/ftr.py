# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser for Microsoft 'Fluster' FTR animations (DirectUI Movie, Vista/7).
Layout derived from DUI70.dll 6.1.7601 (Win7 SP1 x64)."""
import struct

class Reader:
    def __init__(self, data): self.d=data; self.p=0
    def take(self,n):
        if self.p+n>len(self.d): raise EOFError(f'read {n} at {self.p:#x} past end')
        b=self.d[self.p:self.p+n]; self.p+=n; return b
    def u8(self): return self.take(1)[0]
    def u16(self): return struct.unpack('<H',self.take(2))[0]
    def u32(self): return struct.unpack('<I',self.take(4))[0]
    def i32(self): return struct.unpack('<i',self.take(4))[0]
    def f32(self): return struct.unpack('<f',self.take(4))[0]
    def f64(self): return struct.unpack('<d',self.take(8))[0]
    def color(self):  # file bytes R,G,B,A -> (r,g,b,a)
        r,g,b,a=self.take(4); return (r,g,b,a)
    def matrix(self): return tuple(self.f32() for _ in range(6))  # GDI+ m11,m12,m21,m22,dx,dy

TAGS={1:'ShowFrame',2:'DefineShape',22:'DefineShape2',32:'DefineShape3',9:'SetBackgroundColor',
      10:'Tag10',11:'Tag11',12:'DoAction',26:'PlaceObject2',28:'RemoveObject2',39:'DefineSprite'}

def read_fill(r):
    kind=r.u32()
    if kind==0: return {'kind':'solid','color':r.color()}
    if kind in (3,4):
        n=r.u32(); stops=[(r.color(), r.f32()) for _ in range(n)]
        return {'kind':f'gradient{kind}','stops':stops,'matrix':r.matrix()}
    raise ValueError(f'fill kind {kind} at {r.p-4:#x} not yet decoded')

def read_path(r):
    n=r.u32(); pts=[]
    for _ in range(n):
        x=r.f32(); y=r.f32(); t=r.u8(); pts.append((x,y,t))
    return pts

def read_shape(r):
    s={'id':r.u16()}
    s['lines']=[(r.color(), r.f32()) for _ in range(r.u32())]
    s['fills']=[read_fill(r) for _ in range(r.u32())]
    s['paths']=[read_path(r) for _ in range(r.u32())]
    s['draws']=[(r.u32(), r.i32()) for _ in range(r.u32())]
    return s

def read_place(r):
    p={'b9':r.u8(),'has_cxform':r.u8(),'has_matrix':r.u8(),'be':r.u8(),'bf':r.u8(),
       'w10':r.u16(),'w12':r.u16(),'w14':r.u16()}
    if p['has_matrix']: p['matrix']=r.matrix()
    if p['has_cxform']: p['cxform']=[(r.f32(), r.f32()) for _ in range(4)]  # (mult, add) R,G,B,A
    return p

def read_record(r):
    t=r.u32(); name=TAGS.get(t)
    if name is None: raise ValueError(f'unknown record type {t} at {r.p-4:#x}')
    rec={'type':t,'name':name}
    if t==1: pass
    elif t in (2,22,32): rec.update(read_shape(r))
    elif t==9: rec['color']=r.color()
    elif t in (10,11): rec['value']=r.u16()
    elif t==12: rec['a']=r.u32(); rec['b']=r.u16()
    elif t==26: rec.update(read_place(r))
    elif t==28: rec['depth']=r.u16()
    elif t==39:
        rec['id']=r.u16(); rec['records']=[read_record(r) for _ in range(r.u32())]
    return rec

def parse(data):
    r=Reader(data)
    rect=tuple(r.i32() for _ in range(4)); fps=r.f64()
    recs=[read_record(r) for _ in range(r.u32())]
    return {'rect':rect,'fps':fps,'records':recs,'consumed':r.p,'size':len(data)}
