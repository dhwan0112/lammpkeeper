"""pytest bootstrap: put the repo root on sys.path so package imports resolve."""
import os
import sys

# Resolve imports to this checkout, not an older installed wheel. The standalone
# runner performs an equivalent bootstrap without requiring pytest itself.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
