"""Frozen NDJSON entry; no console window is created by the Tauri host."""
import argparse
from pathlib import Path
import sys
from backend.service import main

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--run-tool':
        tool = sys.argv[2]
        from backend.helpers import execute_script
        execute_script(tool, sys.argv[3:])
    elif '--cli' in sys.argv:
        from backend.adapter import load
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--cli', action='store_true')
        parser.add_argument('--package-root', type=Path, required=True)
        options, remaining = parser.parse_known_args()
        root = options.package_root.resolve()
        module = load(root/'OpenWrt-Installer.py', '_compat_cli')
        if (root/'desktop/manifest.json').is_file():
            module.package_root = lambda: root
            sys.exit(module.run_cli(remaining))
        module.B, module.F, module.SCRIPTS = str(root), str(root/'files'), str(root/'scripts')
        sys.argv = ['OpenWrt-Installer.py', *remaining]
        sys.exit(module.run_cli())
    else:
        main()
