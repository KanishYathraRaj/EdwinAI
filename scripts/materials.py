#!/usr/bin/env python3
"""List classroom materials for a Google Classroom course."""

import argparse
import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="List materials for a Google Classroom course.")
    parser.add_argument("course_id", help="Course ID to list materials for")
    args = parser.parse_args()

    _ensure_project_on_path()

    from main import list_materials

    list_materials(args.course_id)


if __name__ == "__main__":
    main()

