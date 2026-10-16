#!/usr/bin/env python3
"""PR #228: verify the shipped Image's own config and full module inventory."""
import argparse
import gzip
from pathlib import Path
import re


def embedded_config(image):
    data = Path(image).read_bytes()
    start = data.find(b'IKCFG_ST')
    end = data.find(b'IKCFG_ED', start + 8) if start >= 0 else -1
    if end < 0:
        raise ValueError('Image has no embedded kernel config')
    try:
        return gzip.decompress(data[start + 8:end]).decode('utf-8')
    except (OSError, EOFError, UnicodeError) as exc:
        raise ValueError('Image has invalid embedded kernel config') from exc


def settings(text):
    return dict(re.findall(r'^(CONFIG_\w+)=(.*)$', text, re.M))


def expanded_check(config, fragment):
    text = Path(fragment).read_text()
    marker = '# Adapted from MU300 PR #228;'
    if marker not in text:
        raise ValueError('Missing expanded kernel feature contract')
    for key, wanted in settings(text[text.index(marker):]).items():
        actual = config.get(key, 'n')
        if actual != wanted and not (wanted == 'm' and actual == 'y'):
            raise ValueError(f'Expanded kernel feature {key}: want {wanted}, got {actual}')


def audit(out, config_name='kernel.config'):
    out = Path(out)
    config = embedded_config(out / 'Image')
    if settings(config) != settings((out / config_name).read_text()):
        raise ValueError('Image embedded configuration differs from ' + config_name)
    expected = (out / 'modules.in-tree').read_text().splitlines()
    if not expected or len({name.replace('-', '_') for name in expected}) != len(expected):
        raise ValueError('Empty or duplicate in-tree module inventory')
    for name in expected:
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.ko', name):
            raise ValueError('Invalid module inventory name: ' + name)
        if not (out / 'modules' / name).is_file():
            raise ValueError('Missing in-tree module: ' + name)
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--config-name', default='kernel.config')
    args = parser.parse_args()
    audit(args.output, args.config_name)
    print('Image embedded config and complete in-tree module inventory verified')
