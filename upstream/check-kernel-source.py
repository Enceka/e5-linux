#!/usr/bin/env python3
"""Require the committed E5 kernel baseline and an unchanged source checkout."""
import argparse
import json
from pathlib import Path
import re
import subprocess

MANIFEST = Path(__file__).with_name('kernel-source.json')


def check(kernel, requirements=None, release_file=None, require_clean=True):
    kernel = Path(kernel).resolve()
    if requirements is None:
        requirements = json.loads(MANIFEST.read_text())
    required = requirements['minimum_revision']
    if not re.fullmatch(r'[0-9a-f]{40}', required):
        raise ValueError('Invalid committed kernel revision')
    def git(*args):
        return subprocess.check_output(['git', '--no-optional-locks', '-C', str(kernel), *args], text=True).strip()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != kernel:
        raise ValueError('Choose the kernel repository root')
    revision = git('rev-parse', 'HEAD')
    result = subprocess.run(['git', '-C', str(kernel), 'merge-base', '--is-ancestor', required, revision],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError('Kernel lacks committed E5 fixes; fetch ' + requirements['repository'] +
                         ' ' + requirements['branch'] + ' (requires ' + required + ')')
    status = git('status', '--porcelain', '--untracked-files=normal')
    if require_clean and status:
        raise ValueError('Kernel source has uncommitted changes:\n' + status)
    if release_file is not None and Path(release_file).read_text().strip().endswith('-dirty'):
        raise ValueError('Kernel output has a dirty source version; use the fixed build version')
    return revision


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('--release-file', type=Path)
    args = parser.parse_args()
    try:
        print('Verified clean committed kernel: ' + check(args.kernel, release_file=args.release_file))
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
