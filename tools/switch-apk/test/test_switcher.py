"""Theme contrast and real misc writes against private regular-file fixtures."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOP = Path(__file__).resolve().parents[1]
JAVA = TOP / 'src/com/minikano/e5switch/MainActivity.java'


def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * w for v, w in zip(values, (.2126, .7152, .0722)))


class Switcher(unittest.TestCase):
    def test_light_dark_text_and_buttons_have_readable_contrast(self):
        styles = {s.attrib['name']: {i.attrib['name']: i.text for i in s}
                  for s in ET.parse(TOP / 'res/values/styles.xml').getroot()}
        for theme in ('Light', 'Dark'):
            dialog = styles['SwitchDialog' + theme]
            background = luminance(dialog['android:colorBackground'])
            colors = [dialog['android:textColorPrimary'], dialog['android:textColorSecondary'],
                      styles['SwitchButton' + theme]['android:textColor']]
            self.assertEqual(dialog['android:forceDarkAllowed'], 'false')
            for color in colors:
                text = luminance(color)
                self.assertGreaterEqual((max(background, text) + .05) / (min(background, text) + .05), 4.5)

    def test_switch_never_mounts_or_rewrites_persistent_selectors(self):
        source = JAVA.read_text(encoding='utf-8')
        for forbidden in ('mount -', 'umount ', '/e5root', '/boot-os', '/default-boot'):
            self.assertNotIn(forbidden, source)
        self.assertIn('SLOT=_a', source)
        for forbidden in ('boot_b', 'BOOT=', 'loglevel=', '请先安装'):
            self.assertNotIn(forbidden, source)
        self.assertIn('Configuration.UI_MODE_NIGHT_YES', source)

    @unittest.skipIf(os.name == 'nt', 'Run the POSIX misc fixture in Linux/WSL')
    def test_read_control_block_without_boot_image_or_tf_card(self):
        source = JAVA.read_text(encoding='utf-8')
        expression = source.split('String read = su(', 1)[1].split('if (read.contains', 1)[0]
        command = ''.join(json.loads(s) for s in re.findall(r'"(?:\\.|[^"\\])*"', expression))
        stock = bytes.fromhex('5f61000042434142010200009f001e000000000000000000000000000be17146')
        with tempfile.TemporaryDirectory(prefix='switch-read-') as folder:
            root = Path(folder)
            before = bytes(2048) + stock + bytes(2048)
            (root / 'misc').write_bytes(before)
            # The only partition fixture is misc: no boot image or rootfs is
            # consulted before a slot can be selected, regardless of storage.
            command = command.replace('BY=/dev/block/by-name', 'BY=' + str(root))
            command = command.replace('[ -b $BY/misc ]', '[ -f $BY/misc ]')
            result = subprocess.run(['sh', '-ec', 'getprop() { echo _a; }; ' + command],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'SLOT=_a\nBC=' + stock.hex() + '\n')
            self.assertEqual((root / 'misc').read_bytes(), before)
            self.assertEqual([p.name for p in root.iterdir()], ['misc'])

    @unittest.skipIf(os.name == 'nt', 'Run the POSIX misc fixture in WSL')
    def test_write_only_changes_the_32_byte_misc_block_and_cleans_scratch(self):
        source = JAVA.read_text(encoding='utf-8')
        expression = source.split('String written = su(', 1)[1].split('Matcher check', 1)[0]
        wanted = bytes.fromhex('5f62000042434142010200009e002f000000000000000000000000009bf8546d')
        escapes = ''.join('\\%03o' % b for b in wanted)
        expression = expression.replace('ArmedBlock.octalEscapes(wanted)', json.dumps(escapes))
        command = ''.join(json.loads(s) for s in re.findall(r'"(?:\\.|[^"\\])*"', expression))
        with tempfile.TemporaryDirectory(prefix='switch-misc-') as folder:
            root = Path(folder); scratch = root / 'tmp'; scratch.mkdir()
            before = bytes(range(256)) * 16
            (root / 'misc').write_bytes(before)
            (root / 'e5root').write_bytes(b'leave this filesystem alone')
            command = command.replace('BY=/dev/block/by-name', 'BY=' + str(root)).replace('/data/local/tmp', str(scratch))
            result = subprocess.run(['sh', '-ec', command], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = (root / 'misc').read_bytes()
            self.assertEqual(after[:2048], before[:2048])
            self.assertEqual(after[2048:2080], wanted)
            self.assertEqual(after[2080:], before[2080:])
            self.assertIn('BC=' + wanted.hex(), result.stdout)
            self.assertEqual((root / 'e5root').read_bytes(), b'leave this filesystem alone')
            self.assertEqual(list(scratch.iterdir()), [])


if __name__ == '__main__': unittest.main()
