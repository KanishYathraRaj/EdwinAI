#!/usr/bin/env python3
"""Run the OAuth flow to refresh or obtain Google Classroom credentials."""

import os
import sys


def _ensure_project_on_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _ensure_project_on_path()

    from main import get_creds

    creds = get_creds()
    print("Token refreshed for:", creds.client_id)


if __name__ == "__main__":
    main()

