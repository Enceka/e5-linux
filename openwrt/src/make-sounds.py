#!/usr/bin/env python3
"""The E5's two sounds, as 48 kHz stereo S16 WAV (what hw:N,3 plays):
beep.wav, two tones for a notification; tick.wav, the volume keys' click.
    make-sounds.py OUTDIR
"""
import math, os, struct, sys, wave

def tone(path, parts, level):
    w = wave.open(path, 'wb')
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
    frames = bytearray()
    for freq, secs in parts:
        n = int(48000 * secs)
        for i in range(n):
            # 5 ms fades: no click at the edges
            env = min(1.0, i / 240, (n - i) / 240)
            v = int(level * 32767 * env * math.sin(2 * math.pi * freq * i / 48000))
            frames += struct.pack('<hh', v, v)
    w.writeframes(bytes(frames)); w.close()

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
tone(os.path.join(out, 'beep.wav'), [(880, 0.18), (0, 0.06), (1320, 0.22)], 0.35)
tone(os.path.join(out, 'tick.wav'), [(1200, 0.05)], 0.3)
