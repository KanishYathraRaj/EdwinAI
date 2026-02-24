#!/usr/bin/env python3
"""Google Classroom + Drive + Forms helper functions."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials",
    "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
    "https://www.googleapis.com/auth/classroom.profile.emails",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]

TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CREDS_FILE = os.path.join(BASE_DIR, "credentials.json")
INTERACTIVE_AUTH = os.getenv("GCR_INTERACTIVE_AUTH", "false").lower() == "true"


def get_creds(interactive_override: bool = False) -> Credentials:
    """Load stored OAuth credentials or trigger the browser flow."""
    creds: Optional[Credentials] = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request  # lazy import
            try:
                creds.refresh(Request())
            except RefreshError:
                # Token is invalid/expired; remove and force re-auth.
                try:
                    os.unlink(TOKEN_FILE)
                except OSError:
                    pass
                raise
        else:
            is_interactive = INTERACTIVE_AUTH or interactive_override
            if not is_interactive:
                raise RefreshError(
                    "OAuth token missing or invalid and interactive auth is disabled. "
                    "Set GCR_INTERACTIVE_AUTH=true and re-auth, or run gcr_client.py locally."
                )
            if not os.path.exists(CREDS_FILE):
                raise FileNotFoundError("credentials.json not found. Download OAuth client credentials and place here.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def svc_classroom(creds: Credentials):
    return build("classroom", "v1", credentials=creds, cache_discovery=False)


def svc_drive(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def svc_forms(creds: Credentials):
    return build("forms", "v1", credentials=creds, cache_discovery=False)


# ---------------------------
# Existing Classroom helpers
# ---------------------------

def list_courses() -> List[Dict]:
    creds = get_creds()
    classroom = svc_classroom(creds)
    courses: List[Dict] = []
    page_token: Optional[str] = None
    while True:
        resp = classroom.courses().list(teacherId="me", pageToken=page_token).execute()
        courses.extend(resp.get("courses", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    for c in courses:
        print(f"{c['id']}\t{c.get('name')}  [{c.get('courseState')}]")
    if not courses:
        print("No courses found (are you a teacher in any Classroom courses?).")
    return courses


def show_course_details(course_id: str) -> None:
    creds = get_creds()
    classroom = svc_classroom(creds)
    course = classroom.courses().get(id=course_id).execute()
    print(json.dumps(course, indent=2))


def list_students(course_id: str) -> List[Dict]:
    creds = get_creds()
    classroom = svc_classroom(creds)
    students: List[Dict] = []
    page_token: Optional[str] = None
    while True:
        resp = classroom.courses().students().list(courseId=course_id, pageToken=page_token).execute()
        students.extend(resp.get("students", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return students


def list_coursework(course_id: str) -> List[Dict]:
    creds = get_creds()
    classroom = svc_classroom(creds)
    items: List[Dict] = []
    page_token: Optional[str] = None
    while True:
        resp = classroom.courses().courseWork().list(courseId=course_id, pageToken=page_token).execute()
        items.extend(resp.get("courseWork", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def list_materials(course_id: str) -> List[Dict]:
    creds = get_creds()
    classroom = svc_classroom(creds)
    items: List[Dict] = []
    page_token: Optional[str] = None
    while True:
        resp = classroom.courses().courseWorkMaterials().list(courseId=course_id, pageToken=page_token).execute()
        items.extend(resp.get("courseWorkMaterial", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def upload_file_to_drive(file_path: str, folder_id: Optional[str] = None) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    creds = get_creds()
    drive = svc_drive(creds)

    media = MediaFileUpload(file_path, resumable=True)
    body = {"name": os.path.basename(file_path)}
    if folder_id:
        body["parents"] = [folder_id]

    uploaded = drive.files().create(body=body, media_body=media, fields="id, name, webViewLink").execute()
    return uploaded["id"]


def post_material_to_class(course_id: str, drive_file_id: str, title: Optional[str] = None, state: str = "PUBLISHED") -> Dict:
    creds = get_creds()
    classroom = svc_classroom(creds)

    request_body = {
        "title": title or "Material",
        "materials": [{"driveFile": {"driveFile": {"id": drive_file_id}}}],
        "state": state,
    }
    return classroom.courses().courseWorkMaterials().create(courseId=course_id, body=request_body).execute()


# ---------------------------
# NEW: Forms helpers
# ---------------------------

def _should_retry_http(err: HttpError) -> bool:
    status = getattr(err.resp, "status", None)
    return status in (429, 500, 503)


def _sleep_backoff(attempt: int):
    time.sleep(min(0.5 * (2 ** attempt), 4.0))


def create_form(title: str) -> Dict:
    creds = get_creds()
    forms = svc_forms(creds)
    return forms.forms().create(body={"info": {"title": title}}).execute()


def forms_batch_update_with_retries(
    form_id: str,
    requests_payload: List[Dict],
    max_retries: int = 4,
    include_form_in_response: bool = False,
) -> Dict:
    creds = get_creds()
    forms = svc_forms(creds)

    last_err = None
    for attempt in range(max_retries):
        try:
            return forms.forms().batchUpdate(
                formId=form_id,
                body={
                    "requests": requests_payload,
                    "includeFormInResponse": include_form_in_response,
                },
            ).execute()
        except HttpError as e:
            last_err = e
            if _should_retry_http(e) and attempt < max_retries - 1:
                _sleep_backoff(attempt)
                continue
            raise
    raise last_err  # pragma: no cover


def get_form_links(form_id: str) -> Dict:
    creds = get_creds()
    forms = svc_forms(creds)
    form = forms.forms().get(formId=form_id).execute()
    return {
        "formId": form_id,
        "responderUri": form.get("responderUri"),
        "title": (form.get("info") or {}).get("title"),
    }


def list_form_responses(form_id: str, page_size: int = 500) -> List[Dict]:
    creds = get_creds()
    forms = svc_forms(creds)

    responses: List[Dict] = []
    page_token: Optional[str] = None

    while True:
        resp = forms.forms().responses().list(
            formId=form_id,
            pageSize=page_size,
            pageToken=page_token,
        ).execute()
        responses.extend(resp.get("responses", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return responses


# ---------------------------
# NEW: Classroom posting (link assignment)
# ---------------------------

def post_quiz_assignment_link(
    course_id: str,
    title: str,
    url: str,
    description: str = "",
    state: str = "PUBLISHED",
    max_points: Optional[int] = None,
) -> Dict:
    """
    Post to Classroom as ASSIGNMENT containing a LINK to responder URL.
    This is reliable (no AttachmentNotVisible).
    """
    creds = get_creds()
    classroom = svc_classroom(creds)

    body = {
        "title": title,
        "description": description or "",
        "workType": "ASSIGNMENT",
        "state": state,
        "materials": [{"link": {"url": url, "title": title}}],
    }
    if max_points is not None:
        body["maxPoints"] = max_points

    return classroom.courses().courseWork().create(courseId=course_id, body=body).execute()


# ---------------------------
# NEW: Grade refresh + optional push to Classroom
# ---------------------------

def _extract_identifier_from_response(resp: Dict, identifier_question_id: str) -> Optional[str]:
    """
    Identifier is a short answer question; stored in resp['answers'][questionId]['textAnswers']['answers'][0]['value']
    """
    answers = resp.get("answers") or {}
    a = answers.get(identifier_question_id)
    if not a:
        return None
    ta = a.get("textAnswers") or {}
    arr = ta.get("answers") or []
    if not arr:
        return None
    val = (arr[0] or {}).get("value")
    if not val:
        return None
    return str(val).strip()


def _extract_choice_value(resp: Dict, question_id: str) -> Optional[str]:
    answers = resp.get("answers") or {}
    a = answers.get(question_id)
    if not a:
        return None
    ta = a.get("textAnswers") or {}
    arr = ta.get("answers") or []
    if not arr:
        return None
    return (arr[0] or {}).get("value")


def compute_scores_from_responses(
    responses: List[Dict],
    identifier_question_id: str,
    answer_key: Dict[str, Dict],
) -> Dict[str, Dict]:
    """
    Returns mapping:
      identifier_value -> { "score": int, "max": int, "responseId": str, "respondentEmail": str|None }
    """
    max_points = sum(int(v.get("points", 0)) for v in answer_key.values())

    out: Dict[str, Dict] = {}

    for r in responses:
        # Prefer respondentEmail if Forms collected it, else use identifier question answer
        respondent_email = r.get("respondentEmail")
        identifier = None

        if respondent_email:
            identifier = str(respondent_email).strip().lower()
        else:
            identifier = _extract_identifier_from_response(r, identifier_question_id)
            if identifier:
                identifier = str(identifier).strip().lower()

        if not identifier:
            continue

        # If quiz graded by Forms, totalScore might exist. But it may be missing if not graded.
        total_score = r.get("totalScore")
        if isinstance(total_score, (int, float)):
            score_val = int(round(float(total_score)))
        else:
            score_val = 0
            for qid, meta in answer_key.items():
                correct = meta.get("correct")
                pts = int(meta.get("points", 0))
                chosen = _extract_choice_value(r, qid)
                if chosen is not None and correct is not None and str(chosen).strip() == str(correct).strip():
                    score_val += pts

        out[identifier] = {
            "score": score_val,
            "max": max_points,
            "responseId": r.get("responseId"),
            "respondentEmail": respondent_email,
            "lastSubmittedTime": r.get("lastSubmittedTime"),
        }

    return out


def build_email_to_classroom_user_map(course_id: str) -> Dict[str, str]:
    """
    email(lowercase) -> classroom userId
    """
    students = list_students(course_id)
    m: Dict[str, str] = {}
    for s in students:
        profile = s.get("profile") or {}
        email = profile.get("emailAddress")
        uid = profile.get("id")
        if email and uid:
            m[str(email).strip().lower()] = str(uid)
    return m


def list_student_submissions(course_id: str, course_work_id: str) -> List[Dict]:
    creds = get_creds()
    classroom = svc_classroom(creds)

    subs: List[Dict] = []
    page_token: Optional[str] = None
    while True:
        resp = classroom.courses().courseWork().studentSubmissions().list(
            courseId=course_id,
            courseWorkId=course_work_id,
            pageToken=page_token,
        ).execute()
        subs.extend(resp.get("studentSubmissions", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return subs


def patch_submission_grade(course_id: str, course_work_id: str, submission_id: str, assigned: int, draft: Optional[int] = None) -> Dict:
    creds = get_creds()
    classroom = svc_classroom(creds)

    body = {
        "assignedGrade": float(assigned),
        "draftGrade": float(draft if draft is not None else assigned),
    }
    return classroom.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=course_work_id,
        id=submission_id,
        updateMask="assignedGrade,draftGrade",
        body=body,
    ).execute()


def push_grades_to_classroom_by_email(
    course_id: str,
    course_work_id: str,
    email_scores: Dict[str, Dict],
) -> Dict:
    """
    Attempts to update assigned/draft grades in Classroom for matching students.
    Returns summary: updated, skipped, errors.
    """
    email_to_uid = build_email_to_classroom_user_map(course_id)
    submissions = list_student_submissions(course_id, course_work_id)

    uid_to_submission_id: Dict[str, str] = {}
    for sub in submissions:
        uid = sub.get("userId")
        sid = sub.get("id")
        if uid and sid:
            uid_to_submission_id[str(uid)] = str(sid)

    updated: List[Dict] = []
    skipped: List[Dict] = []
    errors: List[Dict] = []

    for email, info in email_scores.items():
        uid = email_to_uid.get(email)
        if not uid:
            skipped.append({"email": email, "reason": "student_not_found_in_classroom"})
            continue
        submission_id = uid_to_submission_id.get(uid)
        if not submission_id:
            skipped.append({"email": email, "reason": "no_submission_object_in_classroom_yet"})
            continue

        try:
            patch_submission_grade(course_id, course_work_id, submission_id, assigned=int(info["score"]))
            updated.append({"email": email, "userId": uid, "submissionId": submission_id, "assignedGrade": info["score"]})
        except HttpError as e:
            # Classroom might block grade patch depending on submission state / permissions.
            errors.append({"email": email, "userId": uid, "error": str(e)})

    return {"updated": updated, "skipped": skipped, "errors": errors}


def usage() -> None:
    print(
        "Usage:\n"
        "  python gcr_client.py courses\n"
        "  python gcr_client.py students <COURSE_ID>\n"
    )


def _cli() -> None:
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "courses":
            print(json.dumps(list_courses(), indent=2))
        elif cmd == "students":
            print(json.dumps(list_students(sys.argv[2]), indent=2))
        else:
            usage()
            sys.exit(1)

    except HttpError as exc:
        print(f"HTTP error: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    _cli()
