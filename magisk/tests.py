#!/usr/bin/env python3
"""Boot control tests use regular files, never block devices or reboots."""
import os, struct, subprocess, tempfile, zlib
from pathlib import Path
TOP=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary);exe=root/'bootctl'
 subprocess.run(['cc','-Wall','-Wextra','-Werror','-DE5_BOOTCTL_TEST',str(TOP/'e5-linux-switch/bootctl.c'),'-o',str(exe)],check=True)
 original=bytearray(os.urandom(4096));bc=bytearray(32)
 bc[:4]=b'_a\0\0';bc[4:8]=b'BCAB';bc[8]=1;bc[9]=2;bc[12]=0x9f;bc[14]=0x1e
 bc[16:28]=os.urandom(12);bc[28:]=struct.pack('<I',zlib.crc32(bc[:28]))
 original[2048:2080]=bc
 misc=root/'misc';misc.write_bytes(original)
 def run(*args):return subprocess.run([str(exe),*args,str(misc)],capture_output=True,text=True)
 assert run('check').returncode==0
 assert misc.read_bytes()==original
 backup=root/'backup'
 assert run('arm',str(backup)).returncode==0
 changed=misc.read_bytes();new=changed[2048:2080]
 assert backup.read_bytes()==bytes(bc)
 assert changed[:2048]==original[:2048] and changed[2080:]==original[2080:]
 assert new[:4]==b'_b\0\0' and new[12]==0x9e and new[14]==0x2f
 assert new[16:28]==bc[16:28] and zlib.crc32(new[:28])==struct.unpack('<I',new[28:])[0]
 # Existing backup paths are never clobbered.
 assert run('arm',str(backup)).returncode!=0 and misc.read_bytes()==changed
 for offset,value in [(4,0),(8,2),(9,1),(12,0x1f),(13,1),(15,1),(28,0)]:
  bad=bytearray(bc);bad[offset]=(bad[offset]^1) if offset==28 else value
  if offset!=28:bad[28:]=struct.pack('<I',zlib.crc32(bad[:28]))
  image=bytearray(original);image[2048:2080]=bad;misc.write_bytes(image)
  assert run('arm',str(root/f'bad-{offset}')).returncode!=0
  assert misc.read_bytes()==image and not (root/f'bad-{offset}').exists()
 print('Magisk boot control: CRC, format, Android fallback, backup and bounded write checks passed')
