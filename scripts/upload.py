#!/usr/bin/env python3
"""Upload a local file to Google Drive."""

import argparse
import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a file to Google Drive via the Classroom integration.")
    parser.add_argument("file_path", help="Path to the local file to upload")
    parser.add_argument("folder_id", nargs="?", help="Optional target Drive folder ID")
    args = parser.parse_args()

    _ensure_project_on_path()

    from main import upload_file_to_drive

    file_id = upload_file_to_drive(args.file_path, args.folder_id)
    print(file_id)


if __name__ == "__main__":
    main()

