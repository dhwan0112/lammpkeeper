"""Generic system models, independent of chemical species and force fields.

Importing SpeciesMap needs only the standard library. NumPy-backed geometry is
available through the explicit ``lammpkeeper.core.geometry`` module import.
"""

from .species import SpeciesMap

__all__ = ['SpeciesMap']
