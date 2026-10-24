The build-time generator that writes a hook wrapper for every engine function, the host's export list, and the list of functions that contain each hand-placed hook.

`layouts.py` is the layout check: it compares every class the SDK's headers define against the record in `class-layouts.txt`. To change a layout on purpose before 1.0, run `build-hooked.cmd accept-layouts`, then rebuild every plugin.
