#!/usr/bin/env python3
"""Exercise clean source provenance with real temporary Git histories."""
from pathlib import Path
import json
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



class ManifestSelection(unittest.TestCase):
    """E5_KERNEL_MANIFEST must select an experiment manifest, not edit the default."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.kernel = self.base / 'kernel'
        self.kernel.mkdir()
        subprocess.check_call(['git', '-C', str(self.kernel), 'init', '-q'])
        subprocess.check_call(['git', '-C', str(self.kernel), 'config', 'user.name', 'Manifest test'])
        subprocess.check_call(['git', '-C', str(self.kernel), 'config', 'user.email', 'manifest@example.invalid'])
        (self.kernel / 'driver.c').write_text('kernel\n')
        subprocess.check_call(['git', '-C', str(self.kernel), 'add', '-A'])
        subprocess.check_call(['git', '-C', str(self.kernel), '-c', 'commit.gpgSign=false',
                               'commit', '-qm', 'fixture'])
        self.head = subprocess.check_output(['git', '-C', str(self.kernel), 'rev-parse', 'HEAD'],
                                            text=True).strip()
        self.manifest = self.base / 'kernel-source-7.2.json'
        self.manifest.write_text(json.dumps({'minimum_revision': self.head,
                                             'repository': 'https://example.invalid/kernel.git',
                                             'branch': 'e5-7.2-experiment'}))

    def test_build_maps_the_manifest_into_the_build_container(self):
        # upstream/build.sh mounts the checkout at /work; a relative manifest
        # path must become /work/<file>, not stay relative inside Docker.
        script = (Path(__file__).resolve().parents[1] / 'build.sh').read_text()
        self.assertIn('"/work/${manifest#"$HERE"/}"', script)

    def test_environment_selects_the_experiment_manifest(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'E5_KERNEL_MANIFEST': str(self.manifest)}):
            self.assertEqual(check(self.kernel), self.head)
        # an unrelated minimum in the selected manifest is still rejected
        other = self.base / 'other.json'
        other.write_text(json.dumps({'minimum_revision': '0' * 40,
                                     'repository': 'https://example.invalid/kernel.git',
                                     'branch': 'e5-7.2-experiment'}))
        with mock.patch.dict(os.environ, {'E5_KERNEL_MANIFEST': str(other)}):
            with self.assertRaisesRegex(ValueError, 'lacks committed'):
                check(self.kernel)

if __name__ == '__main__':
    unittest.main()
