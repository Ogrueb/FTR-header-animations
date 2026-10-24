# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extract the six FTR header animations from a Windows shell32 file (standard library only).

Works on:
  Windows Vista / 7:   C:\\Windows\\System32\\shell32.dll (also SysWOW64\\shell32.dll)
  Windows 10:          C:\\Windows\\SystemResources\\shell32.dll.mun
Windows 11 24H2 no longer contains them.

Usage:
  python extract_ftr.py SHELL32_FILE [OUTDIR]        (OUTDIR defaults to ftr_data)

Writes ftr_200_generic.bin ... ftr_205_delete.bin (the names the README and export examples use)
and checks each against the known MD5; the data is byte-identical in Vista SP2, Windows 7 SP1 and
Windows 10 21H2, so a mismatch means a different or modified file.
"""
import hashlib
import os
import struct
import sys

FTR = {
    200: ('ftr_200_generic.bin', 'cdc7839a3f818472411b8781a9c63bba'),
    201: ('ftr_201_copy.bin', 'e7846b9bd5aa6ea5e31f0a0a3de08321'),
    202: ('ftr_202_move.bin', '6ee3df8cc7beec637f25dd53faf97913'),
    203: ('ftr_203_apply_properties.bin', '179ec7200a61bf90669ab2341f576763'),
    204: ('ftr_204_recycle.bin', '8e17feaecbcec87fb7a622ca2c3aee06'),
    205: ('ftr_205_delete.bin', '454806ab2f520cae791d204c674c7cb9'),
}


def resources(data):
    """Yield (type, name, language, bytes) for every resource in a PE file (PE32 or PE32+)."""
    if data[:2] != b'MZ':
        raise ValueError('not a PE file (no MZ header)')
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('not a PE file (no PE signature)')
    nsec, = struct.unpack_from('<H', data, pe + 6)
    optsize, = struct.unpack_from('<H', data, pe + 20)
    opt = pe + 24
    magic, = struct.unpack_from('<H', data, opt)
    datadir = opt + (96 if magic == 0x10B else 112)
    rsrc_rva, rsrc_size = struct.unpack_from('<II', data, datadir + 2 * 8)
    if not rsrc_rva:
        raise ValueError('file has no resources')
    sections = []
    so = opt + optsize
    for _ in range(nsec):
        vsize, va, rsize, raw = struct.unpack_from('<IIII', data, so + 8)
        sections.append((va, max(vsize, rsize), raw))
        so += 40

    def offset(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError(f'RVA {rva:#x} outside all sections')

    base = offset(rsrc_rva)

    def entry_name(value):
        if value & 0x80000000:
            o = base + (value & 0x7FFFFFFF)
            n, = struct.unpack_from('<H', data, o)
            return data[o + 2:o + 2 + 2 * n].decode('utf-16-le')
        return value

    def walk(off, path):
        named, ids = struct.unpack_from('<HH', data, off + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from('<II', data, off + 16 + 8 * i)
            p = path + [entry_name(name)]
            if target & 0x80000000:
                yield from walk(base + (target & 0x7FFFFFFF), p)
            else:
                rva, size = struct.unpack_from('<II', data, base + target)
                yield (*p, data[offset(rva):offset(rva) + size])

    yield from walk(base, [])


def extract(path, outdir='ftr_data'):
    data = open(path, 'rb').read()
    found = {}
    for typ, name, lang, blob in resources(data):
        if isinstance(typ, str) and typ.upper() == 'FTR' and name in FTR and name not in found:
            found[name] = blob
    if not found:
        raise SystemExit(f'{path}: no FTR resources (Windows 11, or not a Vista/7/10 shell32 file)')
    os.makedirs(outdir, exist_ok=True)
    ok = True
    for rid, (fname, md5) in FTR.items():
        blob = found.get(rid)
        if blob is None:
            print(f'FTR {rid}: missing'); ok = False; continue
        out = os.path.join(outdir, fname)
        open(out, 'wb').write(blob)
        good = hashlib.md5(blob).hexdigest() == md5
        ok &= good
        print(f'FTR {rid}: {out} ({len(blob)} bytes) {"MD5 OK" if good else "MD5 MISMATCH"}')
    return ok


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    sys.exit(0 if extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'ftr_data') else 1)
