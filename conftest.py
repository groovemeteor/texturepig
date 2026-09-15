# conftest.py
"""
Make `texture_pig.*` importable from the tests.

The package root is this repo directory itself (it has an __init__.py right
here), and everything imports it as `texture_pig.nodes...` / `texture_pig.ui...`
(see launcher.py, demos/run_editor.py). That only works if the *parent* of
this directory is on sys.path -- so we add it here rather than relying on
whatever happens to be on PYTHONPATH.
"""
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent
_parent = _repo_root.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))
