#!/usr/bin/env python3
"""Exercise clean source provenance with real temporary Git histories."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

check = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'check-kernel-source.py'))['check']


class CommittedKernel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.kernel = self.base / 'kernel'
        self.kernel.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Kernel test')
        self.git('config', 'user.email', 'kernel-test@example.invalid')
        self.source = self.kernel / 'driver.c'
        self.source.write_text('committed driver\n')
        self.commit()
        self.required = self.git('rev-parse', 'HEAD')
        self.requirements = {'minimum_revision': self.required,
                             'repository': 'https://example.invalid/kernel.git', 'branch': 'e5-6.18'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.kernel), *args], text=True).strip()

    def commit(self):
        self.git('add', '-A')
        self.git('-c', 'commit.gpgSign=false', 'commit', '-qm', 'fixture')

    def test_clean_baseline_and_descendant_pass_without_changes(self):
        self.assertEqual(check(self.kernel, self.requirements), self.required)
        self.source.write_text('committed follow-up\n')
        self.commit()
        revision = self.git('rev-parse', 'HEAD')
        self.assertEqual(check(self.kernel, self.requirements), revision)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_tracked_and_staged_changes_are_rejected(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.source.write_text('uncommitted driver\n')
                if staged:
                    self.git('add', 'driver.c')
                with self.assertRaisesRegex(ValueError, 'uncommitted'):
                    check(self.kernel, self.requirements)
                self.assertEqual(self.source.read_text(), 'uncommitted driver\n')

    def test_untracked_source_is_rejected(self):
        (self.kernel / 'new-driver.c').write_text('uncommitted source\n')
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            check(self.kernel, self.requirements)

    def test_missing_or_unrelated_required_history_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'lacks committed'):
            check(self.kernel, {**self.requirements, 'minimum_revision': '0' * 40})
        self.git('checkout', '--orphan', 'unrelated')
        self.source.write_text('different kernel\n')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'lacks committed'):
            check(self.kernel, self.requirements)

    def test_repository_subdirectory_is_rejected(self):
        nested = self.kernel / 'nested'
        nested.mkdir()
        with self.assertRaisesRegex(ValueError, 'root'):
            check(nested, self.requirements)

    def test_model_adaptation_can_check_baseline_with_modified_sources(self):
        self.source.write_text('model-specific driver\n')
        self.assertEqual(check(self.kernel, self.requirements, require_clean=False), self.required)
        with self.assertRaisesRegex(ValueError, 'lacks committed'):
            check(self.kernel, {**self.requirements, 'minimum_revision': '0' * 40}, require_clean=False)

    def test_dirty_output_is_rejected_even_with_clean_sources(self):
        release = self.base / 'kernel.release'
        release.write_text('6.18-e5-dirty\n')
        with self.assertRaisesRegex(ValueError, 'dirty source version'):
            check(self.kernel, self.requirements, release)
        release.write_text('6.18-e5-g' + self.required[:12] + '\n')
        self.assertEqual(check(self.kernel, self.requirements, release), self.required)


if __name__ == '__main__':
    unittest.main()
