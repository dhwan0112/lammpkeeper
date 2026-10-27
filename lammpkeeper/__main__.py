"""Run the same router as the installed ``lkpr`` console script.

Passing the return value to sys.exit preserves dispatcher status codes, while
argparse and sub-CLI SystemExit failures propagate without being swallowed.
"""
import sys

from lammpkeeper.cli import main

sys.exit(main())
