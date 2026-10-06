#!/usr/bin/env python3
"""Selective vendor startup policy with synthetic ELF and fake channel state."""
import errno
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('coldboot', str(TOP / 'rootfs/overlay/opt/e5/e5-modem-coldboot'))
spec = importlib.util.spec_from_loader(loader.name, loader)
cold = importlib.util.module_from_spec(spec); loader.exec_module(cold)
CHARGER = 'console=tty0 modem=shutdown sprdboot.mode=charger'


class ColdBoot(unittest.TestCase):
    def fixture(self):
        data = bytearray(0xE000)
        data[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', data, 18, 183)
        for offset, before, _ in cold.EDITS:data[offset:offset + 4] = before
        return bytes(data)

    def test_only_expected_startup_instructions_change(self):
        data = self.fixture()
        with patch.object(cold, 'KNOWN_SHA256', {hashlib.sha256(data).hexdigest()}):
            result = cold.selective_copy(data)
        assert len(result) == len(data)
        allowed = {i for off, before, _ in cold.EDITS for i in range(off, off + len(before))}
        assert {i for i in range(len(data)) if data[i] != result[i]} <= allowed
        # ARM64 MOVZ immediate decodes to LOAD_CP | LOAD_CH, excluding PM bits.
        instruction = struct.unpack_from('<I', result, 0xD1D0)[0]
        mask = (instruction >> 5) & 0xFFFF
        # In this loader CP=bit1, CH=bit5, SP/PM=bit0. Its CP stop/start
        # condition also includes bit3, so exclude both PM-related bits.
        assert mask == 34 and not (mask & (1 | 8))
        assert result[0xD18C:0xD190] == bytes.fromhex('f3031f2a')

    def test_unknown_and_changed_binaries_refused(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            cold.selective_copy(self.fixture())
        for corruption in ['instruction', 'architecture']:
            data = bytearray(self.fixture())
            if corruption == 'instruction':data[0xD18C] ^= 1
            else:struct.pack_into('<H', data, 18, 62)
            data = bytes(data)
            with patch.object(cold, 'KNOWN_SHA256', {hashlib.sha256(data).hexdigest()}):
                with self.assertRaises(ValueError):cold.selective_copy(data)

    def test_normal_boot_and_online_cp_unchanged(self):
        with patch.object(cold.os, 'open') as opening:
            assert not cold.requires_cold_start('modem=shutdown sprdboot.mode=normal')
            opening.assert_not_called()
        with patch.object(cold.os, 'open', return_value=42), patch.object(cold.os, 'close') as closing:
            assert not cold.requires_cold_start(CHARGER)
            closing.assert_called_once_with(42)

    def test_only_explicitly_offline_charger_boot_is_selected(self):
        for code in (errno.ENODEV, errno.ENOENT):
            with patch.object(cold.os, 'open', side_effect=OSError(code, 'fixture')):
                assert cold.requires_cold_start(CHARGER)
        with patch.object(cold.os, 'open', side_effect=OSError(errno.EBUSY, 'fixture')):
            with self.assertRaisesRegex(ValueError, 'offline'):cold.requires_cold_start(CHARGER)
        with self.assertRaisesRegex(ValueError, 'boot state'):
            cold.requires_cold_start('modem=booting sprdboot.mode=charger')

    def test_private_copy_and_original_preserved(self):
        data = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'vendor/bin').mkdir(parents=True)
            source = root / 'vendor/bin/modem_control'; source.write_bytes(data)
            with patch.object(cold, 'requires_cold_start', return_value=True), patch.object(cold, 'KNOWN_SHA256', {hashlib.sha256(data).hexdigest()}):
                assert cold.prepare(root, CHARGER) == '/tmp/e5-coldboot/modem_control'
            assert source.read_bytes() == data
            target = root / 'tmp/e5-coldboot/modem_control'
            assert target.stat().st_mode & 0o111 and target.read_bytes() != data


if __name__ == '__main__':unittest.main()
