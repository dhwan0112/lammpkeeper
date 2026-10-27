"""Generate deterministic toy slab data for tests, without running LAMMPS.

The Fe grid is not an equilibrated crystal or a GEN-8 real reference system.
Atom 108 deliberately alternates across a 39-Angstrom nonperiodic jump: it is
a boundary probe, not physical dynamics. No physical answer oracle lives here.
"""

import argparse
from itertools import product
from pathlib import Path


BOX = ((0.0, 20.0), (0.0, 20.0), (0.0, 40.0))
PBC = (True, True, False)
STEPS = (0, 10, 20, 30, 40, 50)
DT_FS = 1.0
SURFACE_Z = 8.0
COLUMNS = ('id', 'type', 'x', 'y', 'z')


def frames():
    """Return fresh toy frames with explicit IDs and varied deterministic order."""
    result = []
    for k, timestep in enumerate(STEPS):
        atoms = [
            (atom_id, 1, x, y, z)
            for atom_id, (x, y, z) in enumerate(
                product((4.0, 8.0), (4.0, 8.0), (4.0, 8.0)), start=1
            )
        ]
        atoms.extend([
            (101, 2, (19.8 + 0.4 * k) % 20.0, 2.0, 24.0),
            (102, 2, (0.8 + 0.4 * k) % 20.0, 2.0, 24.0),
            (103, 2, 12.0, (19.8 + 0.3 * k) % 20.0, 24.0),
            (104, 2, 12.0, (0.8 + 0.3 * k) % 20.0, 24.0),
            (105, 2, 16.0, 16.0, 0.2),
            (106, 2, 16.0, 16.0, 39.8),
            (107, 2, 2.0, 12.0, 12.0 - 2.0 * k),
            (108, 2, 10.0, 16.0, 0.4 if k % 2 == 0 else 39.4),
        ])
        # Reordering makes accidental row-index tracking visible in consumers.
        if k % 2:
            atoms.reverse()
        atoms = atoms[k:] + atoms[:k]
        result.append({'timestep': timestep, 'box': BOX, 'atoms': atoms})
    return result


def write_dump(path):
    """Write all toy frames as an explicitly labeled standard LAMMPS dump."""
    path = Path(path)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for frame in frames():
            stream.write(
                'ITEM: TIMESTEP\n{}\nITEM: NUMBER OF ATOMS\n{}\n'
                'ITEM: BOX BOUNDS pp pp ff\n'.format(
                    frame['timestep'], len(frame['atoms'])
                )
            )
            for lower, upper in frame['box']:
                stream.write('{:.17g} {:.17g}\n'.format(lower, upper))
            stream.write('ITEM: ATOMS id type element x y z\n')
            for atom_id, atom_type, x, y, z in frame['atoms']:
                element = {1: 'Fe', 2: 'O'}[atom_type]
                stream.write('{} {} {} {:.17g} {:.17g} {:.17g}\n'.format(
                    atom_id, atom_type, element, x, y, z
                ))
    return path


def write_input(path):
    """Write parser metadata only, not a runnable production simulation input."""
    path = Path(path)
    path.write_text(
        '# Synthetic test metadata only; not a runnable production input.\n'
        '# pair_style zero declares no real force field.\n'
        'units metal\n'
        'boundary p p f\n'
        'atom_style atomic\n'
        'pair_style zero 3.0\n'
        'timestep 0.001\n',
        encoding='utf-8',
    )
    return path


def generate(directory):
    """Create a directory and return its deterministic dump and metadata paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return write_dump(directory / 'slab.dump'), write_input(directory / 'slab.in')


def main():
    """Generate test data at the requested directory and print both paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('outputdir', type=Path)
    args = parser.parse_args()
    for path in generate(args.outputdir):
        print(path)


if __name__ == '__main__':
    main()
