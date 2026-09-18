#!/usr/bin/env python3
"""Probe EGL/GLESv2 on the e5, mainly to prove the Mali UMD <-> kbase handshake.

The interesting question is not "does this app render" but "does the userspace
Mali driver ARM built for this GPU accept the kernel driver this board runs".
That handshake happens inside eglInitialize(): the UMD opens /dev/mali0 and
issues KBASE_IOCTL_VERSION_CHECK with the DDK version it was built against, and
kbase either accepts it or fails the ioctl.  Nothing else in the stack touches
that interface, so a successful eglInitialize plus a GL_RENDERER string is proof
-- and kbase says so on its side too, e.g.

    mali GPU_set_DVFS_table kbase_platform_set_DVFS_table gpu_power_state = 1 ...

Deliberately dependency-free: ctypes only, no compiler, no libEGL.so symlink
needed.  Point it at the blob you want to test:

    EGL_LIB=/opt/mali/libEGL.so.1 GLES_LIB=/opt/mali/libGLESv2.so.2 tools/egl-probe.py

With the fbdev variant, the display itself is /dev/fb0 (CONFIG_FB +
CONFIG_DRM_FBDEV_EMULATION + a KMS driver that calls drm_fbdev_generic_setup()).
Without it EGL still initialises (it falls back to surfaceless), but a window
surface needs the framebuffer; ask for one with:

    EGL_FBDEV_WINDOW=1 EGL_LIB=... tools/egl-probe.py

...which paints the panel through the UMD (fbdev_window is just {u16 width;
u16 height}, see ARM's mali_fbdev_types.h).
"""
import ctypes
import ctypes.util
import os
import sys

# --- EGL --------------------------------------------------------------------
EGL_DEFAULT_DISPLAY = 0
EGL_NO_DISPLAY = 0
EGL_NO_CONTEXT = 0
EGL_NO_SURFACE = 0
EGL_NONE = 0x3038

EGL_ALPHA_SIZE = 0x3021
EGL_BLUE_SIZE = 0x3022
EGL_GREEN_SIZE = 0x3023
EGL_RED_SIZE = 0x3024
EGL_DEPTH_SIZE = 0x3025
EGL_SURFACE_TYPE = 0x3033
EGL_RENDERABLE_TYPE = 0x3040
EGL_VENDOR = 0x3053
EGL_VERSION = 0x3054
EGL_EXTENSIONS = 0x3055
EGL_HEIGHT = 0x3056
EGL_WIDTH = 0x3057
EGL_CLIENT_APIS = 0x308D
EGL_OPENGL_ES_API = 0x30A0
EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_PBUFFER_BIT = 0x0001
EGL_WINDOW_BIT = 0x0004
EGL_OPENGL_ES2_BIT = 0x0004
EGL_OPENGL_ES3_BIT = 0x0040

# --- GBM (what a wlroots/drm compositor actually uses) -----------------------
EGL_PLATFORM_GBM_KHR = 0x31D7
EGL_PLATFORM_WAYLAND_KHR = 0x31D8
GBM_FORMAT_XRGB8888 = 0x34325258     # fourcc 'XR24'
GBM_BO_USE_SCANOUT = 1 << 0
GBM_BO_USE_RENDERING = 1 << 1

ERRORS = {
    0x3000: 'EGL_SUCCESS', 0x3001: 'EGL_NOT_INITIALIZED',
    0x3002: 'EGL_BAD_ACCESS', 0x3003: 'EGL_BAD_ALLOC',
    0x3004: 'EGL_BAD_ATTRIBUTE', 0x3005: 'EGL_BAD_CONFIG',
    0x3006: 'EGL_BAD_CONTEXT', 0x3007: 'EGL_BAD_CURRENT_SURFACE',
    0x3008: 'EGL_BAD_DISPLAY', 0x3009: 'EGL_BAD_MATCH',
    0x300A: 'EGL_BAD_NATIVE_PIXMAP', 0x300B: 'EGL_BAD_NATIVE_WINDOW',
    0x300C: 'EGL_BAD_PARAMETER', 0x300D: 'EGL_BAD_SURFACE',
    0x300E: 'EGL_CONTEXT_LOST',
}

# --- GLES -------------------------------------------------------------------
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_SHADING_LANGUAGE_VERSION = 0x8B8C
GL_NUM_EXTENSIONS = 0x821D
GL_COLOR_BUFFER_BIT = 0x00004000


class FbdevWindow(ctypes.Structure):
    """ARM's platform_fbdev fbdev_window."""
    _fields_ = [('width', ctypes.c_ushort), ('height', ctypes.c_ushort)]


def fail(msg):
    print('FAIL: %s' % msg)
    sys.exit(1)


def egl_error(egl):
    e = egl.eglGetError()
    return '%s (0x%x)' % (ERRORS.get(e, 'unknown'), e)


def load(path, fallback=None):
    lib = path or (ctypes.util.find_library(fallback) if fallback else None)
    if not lib:
        fail('no library given for %s' % (fallback or '?'))
    try:
        return ctypes.CDLL(lib)
    except OSError as exc:
        fail('cannot dlopen %s: %s' % (lib, exc))


def choose_config(egl, dpy, surface_bit, alpha=8, depth=24):
    attr = (ctypes.c_int * 15)(
        EGL_SURFACE_TYPE, surface_bit,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT | EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, alpha,
        EGL_DEPTH_SIZE, depth, EGL_NONE)
    configs = (ctypes.c_void_p * 8)()
    n = ctypes.c_int(0)
    if not egl.eglChooseConfig(dpy, attr, configs, 8, ctypes.byref(n)) or n.value < 1:
        return None, 0
    return configs[0], n.value


def main():
    egl_path = os.environ.get('EGL_LIB')
    gles_path = os.environ.get('GLES_LIB')
    egl = load(egl_path, 'EGL')
    print('libEGL   : %s' % (egl_path or ctypes.util.find_library('EGL')))

    egl.eglGetDisplay.restype = ctypes.c_void_p
    egl.eglGetDisplay.argtypes = [ctypes.c_void_p]
    egl.eglGetError.restype = ctypes.c_int
    egl.eglQueryString.restype = ctypes.c_char_p
    egl.eglQueryString.argtypes = [ctypes.c_void_p, ctypes.c_int]
    egl.eglInitialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_int)]
    egl.eglChooseConfig.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_int)]
    egl.eglCreatePbufferSurface.restype = ctypes.c_void_p
    egl.eglCreatePbufferSurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_int)]
    egl.eglCreateWindowSurface.restype = ctypes.c_void_p
    egl.eglCreateWindowSurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    egl.eglCreateContext.restype = ctypes.c_void_p
    egl.eglCreateContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_int)]
    egl.eglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p]
    egl.eglSwapBuffers.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    egl.eglBindAPI.argtypes = [ctypes.c_uint]

    gbm_surf = 0
    if os.environ.get('EGL_PLATFORM') == 'gbm':
        # The path a compositor takes: a gbm_device on the DRM node, then
        # eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM_KHR, ...).
        gbm = load(os.environ.get('GBM_LIB') or egl_path, 'gbm')
        gbm.gbm_create_device.restype = ctypes.c_void_p
        gbm.gbm_create_device.argtypes = [ctypes.c_int]
        gbm.gbm_surface_create.restype = ctypes.c_void_p
        gbm.gbm_surface_create.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.c_uint32]
        gbm.gbm_surface_has_free_buffers.argtypes = [ctypes.c_void_p]
        node = os.environ.get('DRM_NODE', '/dev/dri/card0')
        fd = os.open(node, os.O_RDWR | os.O_CLOEXEC)
        gdev = gbm.gbm_create_device(fd)
        print('gbm_create_device(%s) -> %s' % (node, hex(gdev) if gdev else 'NULL'))
        if not gdev:
            fail('gbm_create_device failed -- is %s there?' % node)
        # Extension entry points are not always exported as dynamic symbols
        # (ARM's builds only promise them through eglGetProcAddress).
        pfn = getattr(egl, 'eglGetPlatformDisplayEXT', None)
        if pfn is None:
            egl.eglGetProcAddress.restype = ctypes.c_void_p
            egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
            addr = egl.eglGetProcAddress(b'eglGetPlatformDisplayEXT')
            if not addr:
                addr = egl.eglGetProcAddress(b'eglGetPlatformDisplay')
            if addr:
                proto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_int))
                pfn = proto(addr)
        if pfn is None:
            fail('no eglGetPlatformDisplay(EXT) in this build')
        dpy = pfn(EGL_PLATFORM_GBM_KHR, ctypes.c_void_p(gdev), None)
        print('eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM_KHR) -> %s'
              % ('EGL_NO_DISPLAY' if not dpy else hex(dpy)))
        w = int(os.environ.get('EGL_FB_WIDTH', '320'))
        h = int(os.environ.get('EGL_FB_HEIGHT', '480'))
        if hasattr(gbm, 'gbm_bo_create'):
            gbm.gbm_bo_create.restype = ctypes.c_void_p
            gbm.gbm_bo_create.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.c_uint32, ctypes.c_uint32,
                                          ctypes.c_uint32]
        if hasattr(gbm, 'gbm_device_is_format_supported'):
            gbm.gbm_device_is_format_supported.restype = ctypes.c_int
            gbm.gbm_device_is_format_supported.argtypes = [ctypes.c_void_p,
                                                           ctypes.c_uint32,
                                                           ctypes.c_uint32]
        for fmt, fname in ((GBM_FORMAT_XRGB8888, 'XR24'), (0x34325241, 'AR24')):
            if hasattr(gbm, 'gbm_device_is_format_supported'):
                print('  is_format_supported(%s, scanout|rendering) -> %d'
                      % (fname, gbm.gbm_device_is_format_supported(
                          ctypes.c_void_p(gdev), fmt,
                          GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING)))
            if hasattr(gbm, 'gbm_bo_create'):
                bo = gbm.gbm_bo_create(ctypes.c_void_p(gdev), w, h, fmt,
                                       GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING)
                print('  gbm_bo_create(%s %dx%d scanout|rendering) -> %s'
                      % (fname, w, h, hex(bo) if bo else 'NULL'))
            if hasattr(gbm, 'gbm_surface_create_with_modifiers'):
                gbm.gbm_surface_create_with_modifiers.restype = ctypes.c_void_p
                gbm.gbm_surface_create_with_modifiers.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                    ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64), ctypes.c_int]
                mods = (ctypes.c_uint64 * 1)(0)     # DRM_FORMAT_MOD_LINEAR
                s = gbm.gbm_surface_create_with_modifiers(
                    ctypes.c_void_p(gdev), w, h, fmt, mods, 1)
                print('  gbm_surface_create_with_modifiers(%s, LINEAR) -> %s'
                      % (fname, hex(s) if s else 'NULL'))
                if s and not gbm_surf:
                    gbm_surf = s        # the path wlroots takes
            for flags, flname in ((GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING, 'scanout|rendering'),
                                  (GBM_BO_USE_RENDERING, 'rendering'), (0, 'none')):
                s = gbm.gbm_surface_create(ctypes.c_void_p(gdev), w, h, fmt, flags)
                print('  gbm_surface_create(%s, %s) -> %s'
                      % (fname, flname, hex(s) if s else 'NULL'))
                if s and not gbm_surf:
                    gbm_surf = s
        print('gbm_surface_create -> %s' % (hex(gbm_surf) if gbm_surf else 'NULL'))
    elif os.environ.get('EGL_PLATFORM') == 'wayland':
        # What a Wayland *client* (GTK) does: a wl_display, then
        # eglGetPlatformDisplayEXT(EGL_PLATFORM_WAYLAND_KHR, ...).
        wl = load(os.environ.get('WL_LIB') or 'libwayland-client.so.0', 'wayland-client')
        wl.wl_display_connect.restype = ctypes.c_void_p
        wl.wl_display_connect.argtypes = [ctypes.c_char_p]
        wldpy = wl.wl_display_connect(None)
        print('wl_display_connect(%s) -> %s'
              % (os.environ.get('WAYLAND_DISPLAY', '(default)'),
                 hex(wldpy) if wldpy else 'NULL'))
        pfn = getattr(egl, 'eglGetPlatformDisplayEXT', None)
        if pfn is None:
            egl.eglGetProcAddress.restype = ctypes.c_void_p
            egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
            addr = egl.eglGetProcAddress(b'eglGetPlatformDisplayEXT')
            if addr:
                proto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_int))
                pfn = proto(addr)
        if pfn is None:
            fail('this libEGL has no eglGetPlatformDisplayEXT at all')
        dpy = pfn(EGL_PLATFORM_WAYLAND_KHR, ctypes.c_void_p(wldpy), None)
        print('eglGetPlatformDisplayEXT(EGL_PLATFORM_WAYLAND_KHR) -> %s'
              % ('EGL_NO_DISPLAY' if not dpy else hex(dpy)))
    else:
        dpy = egl.eglGetDisplay(ctypes.c_void_p(EGL_DEFAULT_DISPLAY))
        print('eglGetDisplay(DEFAULT) -> %s' % ('EGL_NO_DISPLAY' if not dpy else hex(dpy)))
    if not dpy:
        hint = {'gbm': 'is /dev/dri/card0 there?',
                'wayland': 'does this libEGL have a Wayland platform at all?',
                'default': 'for the fbdev variant this usually means /dev/fb0 is missing'}
        fail('eglGetDisplay failed (%s) -- %s'
             % (egl_error(egl), hint.get(os.environ.get('EGL_PLATFORM', 'default'),
                                         hint['default'])))

    major, minor = ctypes.c_int(0), ctypes.c_int(0)
    if not egl.eglInitialize(dpy, ctypes.byref(major), ctypes.byref(minor)):
        fail('eglInitialize failed (%s) -- the UMD did not accept kbase' % egl_error(egl))
    print('eglInitialize -> OK, EGL %d.%d' % (major.value, minor.value))

    for name, val in (('EGL_VENDOR', EGL_VENDOR), ('EGL_VERSION', EGL_VERSION),
                      ('EGL_CLIENT_APIS', EGL_CLIENT_APIS)):
        s = egl.eglQueryString(dpy, val)
        print('%-16s: %s' % (name, s.decode('utf-8', 'replace') if s else '(null)'))
    ext = (egl.eglQueryString(dpy, EGL_EXTENSIONS) or b'').decode('utf-8', 'replace')
    print('EGL_EXTENSIONS  : %s' % ext)

    egl.eglBindAPI(EGL_OPENGL_ES_API)

    cfg, n = choose_config(egl, dpy, EGL_PBUFFER_BIT)
    if not cfg:
        fail('eglChooseConfig returned no pbuffer configs (%s)' % egl_error(egl))
    print('eglChooseConfig(pbuffer) -> %d config(s)' % n)

    ctx_attr = (ctypes.c_int * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
    ctx = egl.eglCreateContext(dpy, cfg, ctypes.c_void_p(EGL_NO_CONTEXT), ctx_attr)
    if not ctx:
        fail('eglCreateContext failed (%s)' % egl_error(egl))
    print('eglCreateContext -> %s' % hex(ctx))

    pb_attr = (ctypes.c_int * 5)(EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE)
    surf = egl.eglCreatePbufferSurface(dpy, cfg, pb_attr)
    if not surf:
        fail('eglCreatePbufferSurface failed (%s)' % egl_error(egl))
    if not egl.eglMakeCurrent(dpy, surf, surf, ctx):
        fail('eglMakeCurrent(pbuffer) failed (%s)' % egl_error(egl))
    print('pbuffer surface + current -> OK')

    gles = load(gles_path, 'GLESv2')
    gles.glGetString.restype = ctypes.c_char_p
    gles.glGetString.argtypes = [ctypes.c_uint]
    for name, val in (('GL_VENDOR', GL_VENDOR), ('GL_RENDERER', GL_RENDERER),
                      ('GL_VERSION', GL_VERSION),
                      ('GL_SHADING_LANGUAGE_VERSION', GL_SHADING_LANGUAGE_VERSION)):
        s = gles.glGetString(val)
        print('%-28s: %s' % (name, s.decode('utf-8', 'replace') if s else '(null)'))

    n_ext = ctypes.c_int(0)
    gles.glGetIntegerv(GL_NUM_EXTENSIONS, ctypes.byref(n_ext))
    print('GL_NUM_EXTENSIONS           : %d' % n_ext.value)

    gles.glClearColor.argtypes = [ctypes.c_float] * 4
    gles.glClear.argtypes = [ctypes.c_uint]
    gles.glFinish.argtypes = []
    gles.glClearColor(0.0, 0.5, 0.0, 1.0)
    gles.glClear(GL_COLOR_BUFFER_BIT)
    gles.glFinish()
    print('glClear + glFinish -> OK')

    if gbm_surf:
        # A real compositor-shaped surface: GBM surface + EGL window surface.
        egl.eglCreateWindowSurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_int)]
        cfg, n = choose_config(egl, dpy, EGL_WINDOW_BIT,
                               alpha=int(os.environ.get('EGL_FB_ALPHA', '0')))
        wsurf = egl.eglCreateWindowSurface(dpy, cfg, ctypes.c_void_p(gbm_surf), None)
        print('eglCreateWindowSurface(gbm surface) -> %s'
              % ('EGL_NO_SURFACE' if not wsurf else hex(wsurf)))
        if not wsurf:
            fail('eglCreateWindowSurface(gbm) failed (%s)' % egl_error(egl))
        if not egl.eglMakeCurrent(dpy, wsurf, wsurf, ctx):
            fail('eglMakeCurrent(gbm) failed (%s)' % egl_error(egl))
        for rgb in ((0.8, 0.0, 0.0), (0.0, 0.8, 0.0), (0.0, 0.0, 0.8)):
            gles.glClearColor(rgb[0], rgb[1], rgb[2], 1.0)
            gles.glClear(GL_COLOR_BUFFER_BIT)
            gles.glFinish()
            print('eglSwapBuffers -> %s'
                  % ('ok' if egl.eglSwapBuffers(dpy, wsurf) else egl_error(egl)))
        # What a compositor does next: take the front buffer and hand it to KMS.
        if hasattr(gbm, 'gbm_surface_lock_front_buffer'):
            gbm.gbm_surface_lock_front_buffer.restype = ctypes.c_void_p
            gbm.gbm_surface_lock_front_buffer.argtypes = [ctypes.c_void_p]
            gbm.gbm_bo_get_stride.restype = ctypes.c_uint32
            gbm.gbm_bo_get_stride.argtypes = [ctypes.c_void_p]
            gbm.gbm_bo_get_format.restype = ctypes.c_uint32
            gbm.gbm_bo_get_format.argtypes = [ctypes.c_void_p]
            bo = gbm.gbm_surface_lock_front_buffer(ctypes.c_void_p(gbm_surf))
            print('gbm_surface_lock_front_buffer -> %s'
                  % (hex(bo) if bo else 'NULL'))
            if bo:
                print('  bo stride=%d format=0x%x'
                      % (gbm.gbm_bo_get_stride(ctypes.c_void_p(bo)),
                         gbm.gbm_bo_get_format(ctypes.c_void_p(bo))))
        print('GBM-WINDOW-OK')

    if os.environ.get('EGL_FBDEV_WINDOW'):
        fw = FbdevWindow(int(os.environ.get('EGL_FB_WIDTH', '320')),
                         int(os.environ.get('EGL_FB_HEIGHT', '480')))
        # The fbdev is XRGB8888 (transp.length == 0), so ask for a config
        # without alpha -- Mali's fbdev WSI refuses a window config whose
        # native format does not match what /dev/fb0 actually reports.
        cfg, n = choose_config(egl, dpy, EGL_WINDOW_BIT,
                               alpha=int(os.environ.get('EGL_FB_ALPHA', '0')),
                               depth=int(os.environ.get('EGL_FB_DEPTH', '24')))
        if not cfg:
            fail('no window configs (%s)' % egl_error(egl))
        egl.eglGetConfigAttrib.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        for label, attrib in (('CONFIG_ID', 0x3028), ('NATIVE_VISUAL_ID', 0x302E),
                              ('NATIVE_VISUAL_TYPE', 0x302F)):
            val = ctypes.c_int(0)
            egl.eglGetConfigAttrib(dpy, cfg, attrib, ctypes.byref(val))
            print('window config %-17s: %d' % (label, val.value))
        egl.eglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p]
        egl.eglMakeCurrent(dpy, ctypes.c_void_p(EGL_NO_SURFACE),
                           ctypes.c_void_p(EGL_NO_SURFACE), ctypes.c_void_p(EGL_NO_CONTEXT))
        ctx = egl.eglCreateContext(dpy, cfg, ctypes.c_void_p(EGL_NO_CONTEXT), ctx_attr)
        wsurf = egl.eglCreateWindowSurface(dpy, cfg, ctypes.byref(fw), None)
        print('eglCreateWindowSurface(fbdev %dx%d) -> %s'
              % (fw.width, fw.height, 'EGL_NO_SURFACE' if not wsurf else hex(wsurf)))
        if not wsurf:
            fail('glCreateWindowSurface failed (%s) -- is /dev/fb0 there?' % egl_error(egl))
        if not egl.eglMakeCurrent(dpy, wsurf, wsurf, ctx):
            fail('eglMakeCurrent(window) failed (%s)' % egl_error(egl))
        # Three full-screen fills, so the panel changes colour three times.
        for rgb in ((0.8, 0.0, 0.0), (0.0, 0.8, 0.0), (0.0, 0.0, 0.8)):
            gles.glClearColor(rgb[0], rgb[1], rgb[2], 1.0)
            gles.glClear(GL_COLOR_BUFFER_BIT)
            gles.glFinish()
            ok = egl.eglSwapBuffers(dpy, wsurf)
            print('eglSwapBuffers -> %s' % ('ok' if ok else egl_error(egl)))
        print('FBDEV-WINDOW-OK')

    print('HANDSHAKE-OK' if n_ext.value else 'HANDSHAKE-QUESTIONABLE')


if __name__ == '__main__':
    main()