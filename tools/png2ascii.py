#!/usr/bin/env python3
"""Decode a non-interlaced 8-bit RGB PNG and print a coarse ASCII map."""
import sys, zlib, struct

def load(path):
    d = open(path,'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, w, h, bd, ct = 8, b'', 0, 0, 0, 0
    while pos < len(d):
        ln, typ = struct.unpack_from('>I4s', d, pos)
        body = d[pos+8:pos+8+ln]
        if typ == b'IHDR':
            w, h, bd, ct = struct.unpack_from('>IIBB', body, 0)
        elif typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            break
        pos += 12 + ln
    # colour type 2 is RGB, 6 is RGBA (grim produces RGBA when the compositor
    # has an alpha channel); both are 8 bits per channel and filter identically.
    assert bd == 8 and ct in (2, 6), (bd, ct)
    raw = zlib.decompress(idat)
    bpp = 3 if ct == 2 else 4
    stride = w * bpp
    out = bytearray(h*stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if f == 1:
            for i in range(bpp, stride): line[i] = (line[i] + line[i-bpp]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                b = prev[i]; c = prev[i-bpp] if i >= bpp else 0
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[y*stride:(y+1)*stride] = line
        prev = line
    return w, h, out, bpp

def main():
    path = sys.argv[1]
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 106
    w, h, px, bpp = load(path)
    stride = w * bpp
    rows = max(1, int(cols * h / w / 2.1))
    ramp = ' .:-=+*#%@'
    print('image %dx%d -> %dx%d' % (w, h, cols, rows))
    for ry in range(rows):
        line = ''
        for rx in range(cols):
            x0, x1 = rx*w//cols, max(rx*w//cols+1, (rx+1)*w//cols)
            y0, y1 = ry*h//rows, max(ry*h//rows+1, (ry+1)*h//rows)
            tot = n = 0
            for y in range(y0, y1):
                base = y*stride
                for x in range(x0, x1):
                    i = base + x*bpp
                    tot += (px[i]*299 + px[i+1]*587 + px[i+2]*114)//1000
                    n += 1
            v = tot//max(n,1)
            line += ramp[min(len(ramp)-1, v*(len(ramp)-1)//256)]
        print('%3d|%s' % (ry*h//rows, line))

main()
