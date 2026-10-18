# Installer extensions after the device split

These three assets retain the installer-only changes from parent repository
`9095b4a1cc03891e8fc7de3cb840595ad95113e1`: GPT resize/carve operations and
confirmation of the first internal-partition boot. PR #12 intentionally excluded
them from its component migrations.

`boot/stage-installer.py` copies the selected system's assets after device overlay
composition. The initramfs and desktop package builders use the same GPT source.
The pinned component repositories and their working changes are not edited.
Shared radio, board and screen policy remains in the component repositories.
