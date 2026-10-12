"""Used by `driftwatch run`: puts the capture hook in front of one command, with no .pth file installed.

It chains to the user's own sitecustomize (if any) so their setup keeps working.
"""

import os
import sys

try:
    import driftwatch_llm.autostart as _autostart

    _autostart.boot()
except Exception:  # noqa: BLE001
    pass

try:
    from importlib.machinery import PathFinder
    from importlib.util import module_from_spec

    _here = os.path.dirname(os.path.abspath(__file__))
    _others = [p for p in sys.path if os.path.abspath(p or ".") != _here]
    _spec = PathFinder.find_spec("sitecustomize", _others)
    if _spec is not None and _spec.loader is not None:
        _module = module_from_spec(_spec)
        _spec.loader.exec_module(_module)
except Exception:  # noqa: BLE001
    pass
