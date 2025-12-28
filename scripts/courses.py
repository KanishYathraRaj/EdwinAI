#!/usr/bin/env python3
"""List Google Classroom courses for the authenticated teacher."""

import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _ensure_project_on_path()

    from main import list_courses

    list_courses()


if __name__ == "__main__":
    main()

