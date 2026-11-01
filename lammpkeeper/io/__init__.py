"""Validated LAMMPS metadata models, independent of domain analysis code.

Box describes a physical restricted cell; importing it does not read files or
resolve unknown periodic flags. Legacy readers remain separate entry points.
"""

from .box import Box
from .metadata import MetadataField, RunMetadata, derive_dt_fs

__all__ = ['Box', 'MetadataField', 'RunMetadata', 'derive_dt_fs']
