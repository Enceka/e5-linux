#!/usr/bin/env python3
"""Dump /dev/fb0's fix/var screeninfo the way the Mali fbdev UMD sees it.

Why: the UMD's fbdev WSI allocates its window surface out of the framebuffer, so
it cares about smem_start (a physical address), line_length and, in particular,
whether yres_virtual leaves room for more than one screen.  The DRM generic
fbdev (drm_fbdev_generic_setup) is known to leave smem_start = 0 and
yres_virtual = yres, which is enough for fbcon and not always enough for a GPU
WSI -- this tool is how that gets told apart from other failures.

    tools/fbdev-info.py [/dev/fb0]
"""
import ctypes
import fcntl
import sys

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
FBIOPAN_DISPLAY = 0x4606


class FbBitfield(ctypes.Structure):
    _fields_ = [('offset', ctypes.c_uint32), ('length', ctypes.c_uint32),
                ('msb_right', ctypes.c_uint32)]


class FbVarScreeninfo(ctypes.Structure):
    _fields_ = [
        ('xres', ctypes.c_uint32), ('yres', ctypes.c_uint32),
        ('xres_virtual', ctypes.c_uint32), ('yres_virtual', ctypes.c_uint32),
        ('xoffset', ctypes.c_uint32), ('yoffset', ctypes.c_uint32),
        ('bits_per_pixel', ctypes.c_uint32), ('grayscale', ctypes.c_uint32),
        ('red', FbBitfield), ('green', FbBitfield), ('blue', FbBitfield),
        ('transp', FbBitfield),
        ('nonstd', ctypes.c_uint32), ('activate', ctypes.c_uint32),
        ('height', ctypes.c_uint32), ('width', ctypes.c_uint32),
        ('accel_flags', ctypes.c_uint32), ('pixclock', ctypes.c_uint32),
        ('left_margin', ctypes.c_uint32), ('right_margin', ctypes.c_uint32),
        ('upper_margin', ctypes.c_uint32), ('lower_margin', ctypes.c_uint32),
        ('hsync_len', ctypes.c_uint32), ('vsync_len', ctypes.c_uint32),
        ('sync', ctypes.c_uint32), ('vmode', ctypes.c_uint32),
        ('rotate', ctypes.c_uint32), ('colorspace', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32 * 4),
    ]


class FbFixScreeninfo(ctypes.Structure):
    _fields_ = [
        ('id', ctypes.c_char * 16),
        ('smem_start', ctypes.c_ulong),
        ('smem_len', ctypes.c_uint32),
        ('type', ctypes.c_uint32),
        ('type_aux', ctypes.c_uint32),
        ('visual', ctypes.c_uint32),
        ('xpanstep', ctypes.c_uint16), ('ypanstep', ctypes.c_uint16),
        ('ywrapstep', ctypes.c_uint16),
        ('line_length', ctypes.c_uint32),
        ('mmio_start', ctypes.c_ulong),
        ('mmio_len', ctypes.c_uint32),
        ('accel', ctypes.c_uint32),
        ('capabilities', ctypes.c_uint16),
        ('reserved', ctypes.c_uint16 * 2),
    ]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/dev/fb0'
    var = FbVarScreeninfo()
    fix = FbFixScreeninfo()
    try:
        fd = open(path, 'rb')
    except OSError as exc:
        sys.exit('%s: %s' % (path, exc))
    fcntl.ioctl(fd, FBIOGET_VSCREENINFO, var, True)
    fcntl.ioctl(fd, FBIOGET_FSCREENINFO, fix, True)

    print('%s' % path)
    print('  id                : %s' % fix.id.decode('utf-8', 'replace'))
    print('  smem_start        : 0x%x   <- 0 means "no physical address"' % fix.smem_start)
    print('  smem_len          : %d' % fix.smem_len)
    print('  line_length       : %d' % fix.line_length)
    print('  visual/type       : %d / %d' % (fix.visual, fix.type))
    print('  xpanstep/ypanstep : %d / %d' % (fix.xpanstep, fix.ypanstep))
    print('  capabilities      : 0x%x' % fix.capabilities)
    print('  xres x yres       : %d x %d' % (var.xres, var.yres))
    print('  virtual           : %d x %d' % (var.xres_virtual, var.yres_virtual))
    print('  xoffset/yoffset   : %d / %d' % (var.xoffset, var.yoffset))
    print('  bits_per_pixel    : %d' % var.bits_per_pixel)
    print('  red/green/blue    : %d:%d / %d:%d / %d:%d'
          % (var.red.offset, var.red.length, var.green.offset, var.green.length,
             var.blue.offset, var.blue.length))
    print('  transp            : %d:%d' % (var.transp.offset, var.transp.length))
    print('  activate          : 0x%x' % var.activate)
    print('  framebuffers      : %d screen(s) of %d lines'
          % (var.yres_virtual // var.yres if var.yres else 0, var.yres))
    fd.close()


if __name__ == '__main__':
    main()
