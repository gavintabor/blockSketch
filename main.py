#!/usr/bin/env python3
"""
blockSketch – interactive viewer/editor for OpenFOAM blockMeshDict files.

Usage:
    python main.py [path/to/blockMeshDict]

With no argument, searches the current working directory for a blockMeshDict
in the standard OpenFOAM locations.  If none is found, offers to create one.
"""
import sys
import os

# Ensure the package directory is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from desktop import app

# ---------------------------------------------------------------------------
# Minimal blockMeshDict written when the user requests a new empty file
# ---------------------------------------------------------------------------
_EMPTY_DICT = """\
FoamFile
{
    version   2.0;
    format    ascii;
    class     dictionary;
    object    blockMeshDict;
}

scale 1.0;
vertices ( );
blocks ( );
edges ( );
boundary ( );
"""

# Standard search order (relative to cwd)
_SEARCH_LOCATIONS = [
    os.path.join('system', 'blockMeshDict'),
    os.path.join('constant', 'polyMesh', 'blockMeshDict'),
]


def _find_blockmeshdict() -> str | None:
    """Return the path of the first blockMeshDict found, or None."""
    for rel in _SEARCH_LOCATIONS:
        path = os.path.join(os.getcwd(), rel)
        if os.path.isfile(path):
            return path
    return None


def _create_empty(path: str) -> None:
    """Write a minimal blockMeshDict to *path*, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(_EMPTY_DICT)


def main() -> None:
    explicit_path = len(sys.argv) > 1

    if explicit_path:
        # User supplied a path — validate it immediately.
        path = sys.argv[1]
        if not os.path.isfile(path):
            print(f'blockSketch: error: file not found: {path}')
            sys.exit(1)
    else:
        # Auto-search standard locations.
        path = _find_blockmeshdict()

        if path is None:
            # Offer to create a new file.
            print('blockSketch: no blockMeshDict found in standard locations.')
            try:
                answer = input('Create a new empty blockMeshDict? [Y/n]: ').strip().lower()
            except EOFError:
                answer = ''

            if answer in ('', 'y', 'yes'):
                path = os.path.join(os.getcwd(), 'system', 'blockMeshDict')
                _create_empty(path)
                print(f'Created: {path}')
            else:
                print('Exiting.')
                sys.exit(0)

    print(f'Opening: {path}')
    app.launch(path)


if __name__ == '__main__':
    main()
