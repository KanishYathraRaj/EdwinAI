#!/usr/bin/env python3
"""List students enrolled in a Google Classroom course."""

import argparse
import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="List students in a Google Classroom course.")
    parser.add_argument("course_id", help="Course ID to list students for")
    args = parser.parse_args()

    _ensure_project_on_path()

    from main import list_students

    list_students(args.course_id)


if __name__ == "__main__":
    main()

