"""Google Classroom REST integration for the Flask app.

This module wraps the existing CLI-oriented helpers defined in the project
root `main.py` and exposes them through HTTP routes. Use
`register_gcr_routes(app)` from `EdwinAI.main` to mount these routes onto the
Flask application without introducing circular imports.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from googleapiclient.errors import HttpError
from werkzeug.utils import secure_filename

@lru_cache(maxsize=1)
def _cli_module():
    """Lazy import of the CLI helpers to avoid circular imports."""
    # Ensure project root is in path to import root main.py
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return importlib.import_module("main")


def _call(helper_name: str, *args, **kwargs):
    helper = getattr(_cli_module(), helper_name)
    return helper(*args, **kwargs)


gcr_bp = Blueprint("gcr", __name__, url_prefix="/gcr")


def _handle_http_error(err: HttpError):
    """Convert a Google API HttpError into a JSON Flask response."""

    message: Dict[str, Any] = {"error": str(err), "status": getattr(err.resp, "status", None)}
    if err.content:
        try:
            message["details"] = json.loads(err.content.decode())
        except Exception:
            message["raw_content"] = err.content.decode(errors="ignore")
    return jsonify(message), getattr(err.resp, "status", 500)


@gcr_bp.route("/auth", methods=["POST"])
def trigger_auth():
    """Run the OAuth flow to ensure Classroom credentials are available."""

    try:
        creds = _call("get_creds")
    except HttpError as err:
        return _handle_http_error(err)
    except Exception as exc:  # OAuth flow may raise other exceptions
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "client_id": getattr(creds, "client_id", None),
            "scopes": creds.scopes,
            "token_uri": getattr(creds, "token_uri", None),
        }
    )


@gcr_bp.route("/courses", methods=["GET"])
def get_courses():
    try:
        courses = _call("list_courses")
        return jsonify({"courses": courses})
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/courses/<course_id>", methods=["GET"])
def get_course_details(course_id: str):
    try:
        creds = _call("get_creds")
        classroom = _call("svc_classroom", creds)
        course = classroom.courses().get(id=course_id).execute()
        return jsonify(course)
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/courses/<course_id>/students", methods=["GET"])
def get_students(course_id: str):
    try:
        students = _call("list_students", course_id)
        return jsonify({"students": students})
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/courses/<course_id>/coursework", methods=["GET"])
def get_coursework(course_id: str):
    try:
        coursework = _call("list_coursework", course_id)
        return jsonify({"coursework": coursework})
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/courses/<course_id>/materials", methods=["GET"])
def get_materials(course_id: str):
    try:
        materials = _call("list_materials", course_id)
        return jsonify({"materials": materials})
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/drive/upload", methods=["POST"])
def upload_drive_file():
    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        return jsonify({"error": "Missing file in form-data under key 'file'"}), 400

    folder_id = request.form.get("folderId") or request.args.get("folderId")

    safe_name = secure_filename(uploaded_file.filename or "upload")
    with tempfile.NamedTemporaryFile(prefix="gcr_upload_", delete=False) as tmp:
        tmp_path = tmp.name
        uploaded_file.save(tmp_path)

    try:
        os.rename(tmp_path, tmp_path := f"{tmp_path}_{safe_name}")
    except OSError:
        pass

    try:
        drive_id = _call("upload_file_to_drive", tmp_path, folder_id)
        response = {"fileId": drive_id}
    except HttpError as err:
        return _handle_http_error(err)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify(response)


@gcr_bp.route("/courses/<course_id>/materials/attach", methods=["POST"])
def attach_drive_file(course_id: str):
    body = request.get_json(silent=True) or {}
    drive_file_id = body.get("drive_file_id") or body.get("driveFileId")
    if not drive_file_id:
        return jsonify({"error": "drive_file_id is required"}), 400

    title = body.get("title")
    state = body.get("state", "PUBLISHED")

    try:
        material = _call("post_material_to_class", course_id, drive_file_id, title, state)
        return jsonify(material)
    except HttpError as err:
        return _handle_http_error(err)


@gcr_bp.route("/courses/<course_id>/materials/upload", methods=["POST"])
def upload_and_attach(course_id: str):
    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        return jsonify({"error": "Missing file in form-data under key 'file'"}), 400

    title = request.form.get("title") or request.args.get("title")

    safe_name = secure_filename(uploaded_file.filename or "upload")
    with tempfile.NamedTemporaryFile(prefix="gcr_upload_attach_", delete=False) as tmp:
        tmp_path = tmp.name
        uploaded_file.save(tmp_path)

    try:
        os.rename(tmp_path, tmp_path := f"{tmp_path}_{safe_name}")
    except OSError:
        pass

    try:
        drive_id = _call("upload_file_to_drive", tmp_path)
        material = _call("post_material_to_class", course_id, drive_id, title)
        response = {"fileId": drive_id, "material": material}
    except HttpError as err:
        return _handle_http_error(err)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify(response)

def register_gcr_routes(app):
    """Attach the Google Classroom blueprint to the provided Flask app."""

    app.register_blueprint(gcr_bp)


__all__ = ["gcr_bp", "register_gcr_routes"]

