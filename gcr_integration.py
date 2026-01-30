"""Google Classroom REST integration for the Flask app."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
from functools import lru_cache
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from werkzeug.utils import secure_filename

# Lazy import gcr_client
@lru_cache(maxsize=1)
def _cli_module():
    return importlib.import_module("gcr_client")


def _call(helper_name: str, *args, **kwargs):
    helper = getattr(_cli_module(), helper_name)
    return helper(*args, **kwargs)


gcr_bp = Blueprint("gcr", __name__, url_prefix="/gcr")


def _handle_http_error(err: HttpError):
    message: Dict[str, Any] = {"error": str(err), "status": getattr(err.resp, "status", None)}
    if err.content:
        try:
            message["details"] = json.loads(err.content.decode())
        except Exception:
            message["raw_content"] = err.content.decode(errors="ignore")
    return jsonify(message), getattr(err.resp, "status", 500)


def _handle_auth_error(err: RefreshError):
    message = {
        "error": str(err),
        "code": "INVALID_GRANT",
        "hint": "OAuth token is invalid/expired. Delete token.json and re-auth via /gcr/auth (set GCR_INTERACTIVE_AUTH=true) or run gcr_client.py.",
    }
    return jsonify(message), 401


@gcr_bp.route("/auth", methods=["POST"])
def trigger_auth():
    try:
        creds = _call("get_creds")
    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
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
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@gcr_bp.route("/courses/<course_id>", methods=["GET"])
def get_course_details(course_id: str):
    try:
        creds = _call("get_creds")
        classroom = _call("svc_classroom", creds)
        course = classroom.courses().get(id=course_id).execute()
        return jsonify(course)
    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@gcr_bp.route("/courses/<course_id>/students", methods=["GET"])
def get_students(course_id: str):
    try:
        students = _call("list_students", course_id)
        return jsonify({"students": students})
    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@gcr_bp.route("/courses/<course_id>/coursework", methods=["GET"])
def get_coursework(course_id: str):
    try:
        coursework = _call("list_coursework", course_id)
        return jsonify({"coursework": coursework})
    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@gcr_bp.route("/courses/<course_id>/materials", methods=["GET"])
def get_materials(course_id: str):
    try:
        materials = _call("list_materials", course_id)
        return jsonify({"materials": materials})
    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
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
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify(response)


# -----------------------------
# NEW: Refresh Grades (GET)
# -----------------------------
@gcr_bp.route("/courses/<course_id>/coursework/<coursework_id>/grades", methods=["GET"])
def fetch_and_store_grades(course_id: str, coursework_id: str):
    """
    UI refresh button should call:

      GET /gcr/courses/<course_id>/coursework/<coursework_id>/grades?user_id=u1&subject_id=s1

    It will:
      - read latest_quiz metadata from Firestore
      - fetch Forms responses
      - compute scores (use totalScore if available; else compute from answer_key)
      - store computed grades in Firestore
      - optionally push to Classroom (push_to_classroom=true)
    """
    try:
        user_id = request.args.get("user_id")
        subject_id = request.args.get("subject_id")
        push_to_classroom = (request.args.get("push_to_classroom", "true").lower() == "true")

        if not user_id or not subject_id:
            return jsonify({"error": "user_id and subject_id are required as query params"}), 400

        # Import firestore lazily to avoid circulars
        from firebase_admin import firestore
        db = firestore.client()

        doc_ref = db.collection("users").document(user_id).collection("subjects").document(subject_id)
        snap = doc_ref.get()
        if not snap.exists:
            return jsonify({"error": "No subject doc found for user_id/subject_id"}), 404

        subj = snap.to_dict() or {}
        latest = (subj.get("latest_quiz") or {})

        form_id = latest.get("form_id")
        identifier_question_id = latest.get("identifier_question_id")
        answer_key = latest.get("answer_key") or {}

        if not form_id or not identifier_question_id or not answer_key:
            return jsonify({
                "error": "Missing quiz metadata in Firestore (form_id / identifier_question_id / answer_key)",
                "latest_quiz": latest
            }), 400

        # 1) fetch responses
        responses = _call("list_form_responses", form_id)

        # 2) compute scores keyed by email/identifier
        email_scores = _call("compute_scores_from_responses", responses, identifier_question_id, answer_key)

        # 3) store in firestore under latest_quiz.grades
        grades_obj = {
            "computed_at": firestore.SERVER_TIMESTAMP,
            "course_id": course_id,
            "coursework_id": coursework_id,
            "form_id": form_id,
            "count": len(email_scores),
            "by_email": email_scores,
        }
        doc_ref.set({"latest_quiz": {"grades": grades_obj}}, merge=True)

        # 4) optionally push to Classroom
        classroom_push = None
        if push_to_classroom:
            try:
                classroom_push = _call("push_grades_to_classroom_by_email", course_id, coursework_id, email_scores)
            except Exception as e:
                classroom_push = {"error": str(e)}

        return jsonify({
            "ok": True,
            "grades": grades_obj,
            "classroom_push": classroom_push,
        })

    except HttpError as err:
        return _handle_http_error(err)
    except RefreshError as err:
        return _handle_auth_error(err)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def register_gcr_routes(app):
    app.register_blueprint(gcr_bp)


__all__ = ["gcr_bp", "register_gcr_routes"]
