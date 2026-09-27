#!/usr/bin/env python3
"""A platform driver's remove callback returns void since 6.11: convert a vendor driver's `int` one.

usage: remove-void.py file.c [function]   (default: the .remove = <name> of the file's platform_driver)

The function's `return 0;` statements are dropped (the last one) or become `return;` (early ones); any other
return value stops the conversion, since it would be an error the new signature cannot report.
"""
import re
import sys

path = sys.argv[1]
s = open(path).read()
name = sys.argv[2] if len(sys.argv) > 2 else re.search(r'\.remove\s*=\s*(\w+)\s*,', s).group(1)
m = re.search(r'^static\s+int\s+(%s)\((struct platform_device \*\w+)\)\n\{\n' % name, s, re.M)
if not m:
    sys.exit(f'{path}: no "static int {name}(struct platform_device *)" to convert')
start = m.end()
depth, i = 1, start
while depth:
    depth += {'{': 1, '}': -1}.get(s[i], 0)
    i += 1
body = s[start:i - 1]
others = [r for r in re.findall(r'return\s+([^;]+);', body) if r.strip() != '0']
if others:
    sys.exit(f'{path}: {name} returns {others}: convert by hand')
body = re.sub(r'\n\n\treturn 0;\n$', '\n', body)          # the final return, with the blank line before it
body = re.sub(r'\n\treturn 0;\n$', '\n', body)
body = re.sub(r'return 0;', 'return;', body)               # early returns
s = s[:m.start()] + f'static void {name}({m.group(2)})\n{{\n' + body + s[i - 1:]
open(path, 'w').write(s)
print(f'{path}: {name} returns void')
