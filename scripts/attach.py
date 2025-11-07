#!/usr/bin/env python3
"""Attach an existing Drive file as Classroom material."""

import argparse
import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach an existing Drive file to a Google Classroom course as material.")
    parser.add_argument("course_id", help="Course ID to post material in")
    parser.add_argument("drive_file_id", help="Drive file ID to attach")
    parser.add_argument("title", nargs="?", help="Optional material title")
    args = parser.parse_args()

    _ensure_project_on_path()

    from main import post_material_to_class

    post_material_to_class(args.course_id, args.drive_file_id, args.title)


if __name__ == "__main__":
    main()

