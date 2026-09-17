#!/usr/bin/env python3
"""Generate modules.dep without depmod, for build hosts that have no kmod (macOS).

depmod's rule is "a module depends on the modules that export the symbols it
references", and the kernel build already records both halves of that:

  * Module.symvers  -> which module exports each symbol
  * each .ko        -> which symbols it references (its undefined symbols)

usage: gen-modules-dep.py MODULE_TREE        (prints modules.dep on stdout)

MODULE_TREE is the tree boot/stage-modules.sh builds for depmod: the .ko files
under kernel/... and Module.symvers at its root.  Keys are printed as the paths
relative to that root, which is what boot/gen-module-order.py consumes.

Module.symvers names the exporting module the way the build tree does -- e.g.
"net/wireless/cfg80211", not "cfg80211" -- so the lookup below matches on path
suffix and works whether the tree is a build output or the staged copy.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_nm():
    for candidate in (os.environ.get("NM"), "llvm-nm", "nm"):
        if candidate and shutil.which(candidate):
            return candidate
    sys.exit("no nm found (need llvm-nm from LLVM)")


def undefined_symbols(ko, nm):
    out = subprocess.run([nm, "-u", str(ko)], capture_output=True, text=True).stdout
    syms = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("U", "w", "v"):
            syms.append(parts[1])
    return syms


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tree = Path(sys.argv[1]).resolve()
    nm = find_nm()

    owner = {}
    symvers = tree / "Module.symvers"
    if symvers.exists():
        for line in symvers.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 3:
                owner[fields[1]] = fields[2]

    kos = sorted(tree.rglob("*.ko"))
    key_of = {ko.stem: str(ko.relative_to(tree)) for ko in kos}
    id_of = {str(ko.relative_to(tree))[:-3]: str(ko.relative_to(tree)) for ko in kos}

    def provider(owner_id):
        if owner_id in id_of:
            return id_of[owner_id]
        tail = "/" + owner_id
        for ident, path in id_of.items():
            if ident.endswith(tail):
                return path
        return None

    for ko in kos:
        deps = []
        for sym in undefined_symbols(ko, nm):
            who = owner.get(sym)
            if not who or who == "vmlinux":
                continue
            dep = provider(who)
            if dep and dep != str(ko.relative_to(tree)) and dep not in deps:
                deps.append(dep)
        print("%s: %s" % (str(ko.relative_to(tree)), " ".join(sorted(deps))))


if __name__ == "__main__":
    main()
