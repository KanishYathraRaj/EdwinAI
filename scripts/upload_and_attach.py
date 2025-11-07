#!/usr/bin/env python3
"""Upload a file to Drive and attach it to a Classroom course."""

import argparse
import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a file to Drive and attach it to a Google Classroom course.")
    parser.add_argument("course_id", help="Course ID to post material in")
    parser.add_argument("file_path", help="Local file to upload")
    parser.add_argument("title", nargs="?", help="Optional material title")
    args = parser.parse_args()

    _ensure_project_on_path()

    from main import post_material_to_class, upload_file_to_drive

    file_id = upload_file_to_drive(args.file_path)
    post_material_to_class(args.course_id, file_id, args.title)


if __name__ == "__main__":
    main()

