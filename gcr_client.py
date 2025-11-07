#!/usr/bin/env python3
"""Google Classroom helper CLI and reusable functions."""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

from google.oauth2.credentials import Credentials
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
]

TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CREDS_FILE = os.path.join(BASE_DIR, "credentials.json")


def get_creds() -> Credentials:
    """Load stored OAuth credentials or trigger the browser flow."""

    creds: Optional[Credentials] = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request  # lazy import to avoid dependency when unused

            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                raise FileNotFoundError(
                    "credentials.json not found. Download OAuth client credentials and place here."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def svc_classroom(creds: Credentials):
    return build("classroom", "v1", credentials=creds, cache_discovery=False)


def svc_drive(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


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
    print(
        json.dumps(
            {
                "id": course["id"],
                "name": course.get("name"),
                "section": course.get("section"),
                "room": course.get("room"),
                "ownerId": course.get("ownerId"),
                "state": course.get("courseState"),
                "descriptionHeading": course.get("descriptionHeading"),
                "description": course.get("description"),
                "calendarId": course.get("calendarId"),
                "courseGroupEmail": course.get("courseGroupEmail"),
                "teacherGroupEmail": course.get("teacherGroupEmail"),
                "alternateLink": course.get("alternateLink"),
            },
            indent=2,
        )
    )


def list_students(course_id: str):
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

    print("gc_user_id\tName\tEmail\tEnrollmentStatus")
    for student in students:
        profile = student.get("profile", {})
        name = profile.get("name", {}).get("fullName")
        email = profile.get("emailAddress")
        status = student.get("studentWorkFolder", {}).get("title", "ACTIVE")
        print(f"{profile.get('id')}\t{name}\t{email}\t{status}")

    print(f"\nTotal students: {len(students)}")
    return students


def list_coursework(course_id: str):
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

    if not items:
        print("No coursework found.")
        return items

    for cw in items:
        print(
            f"{cw['id']}\t{cw.get('title')}  ({cw.get('workType')})  "
            f"state={cw.get('state')}  due={cw.get('dueDate')}"
        )
    print(f"\nTotal coursework: {len(items)}")
    return items


def list_materials(course_id: str):
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

    if not items:
        print("No course materials found.")
        return items

    for material in items:
        drive_bits: List[str] = []
        for mat in material.get("materials", []):
            if "driveFile" in mat:
                drive_file = mat["driveFile"].get("driveFile", {})
                drive_bits.append(f"Drive:{drive_file.get('title')} ({drive_file.get('id')})")
            if "link" in mat:
                link = mat["link"]
                drive_bits.append(f"Link:{link.get('title')} {link.get('url')}")
            if "youtubeVideo" in mat:
                drive_bits.append(f"YouTube:{mat['youtubeVideo'].get('title')}")
        print(
            f"{material['id']}\t{material.get('title')}  state={material.get('state')}  "
            f"-> {' | '.join(drive_bits)}"
        )
    print(f"\nTotal materials: {len(items)}")
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

    uploaded = (
        drive.files()
        .create(body=body, media_body=media, fields="id, name, webViewLink")
        .execute()
    )
    print(
        f"Uploaded to Drive: {uploaded.get('name')} ({uploaded['id']})  {uploaded.get('webViewLink')}"
    )
    return uploaded["id"]


def post_material_to_class(
    course_id: str, drive_file_id: str, title: Optional[str] = None, state: str = "PUBLISHED"
):
    creds = get_creds()
    classroom = svc_classroom(creds)

    request_body = {
        "title": title or "Material",
        "materials": [{"driveFile": {"driveFile": {"id": drive_file_id}}}],
        "state": state,
    }
    created = (
        classroom.courses()
        .courseWorkMaterials()
        .create(courseId=course_id, body=request_body)
        .execute()
    )
    print(f"Created material: {created.get('id')}  title={created.get('title')}")
    return created


def usage() -> None:
    print(
        "Usage:\n"
        "  python main.py courses\n"
        "  python main.py course <COURSE_ID>\n"
        "  python main.py students <COURSE_ID>\n"
        "  python main.py coursework <COURSE_ID>\n"
        "  python main.py materials <COURSE_ID>\n"
        "  python main.py upload <FILE_PATH> [DRIVE_FOLDER_ID]\n"
        "  python main.py attach <COURSE_ID> <DRIVE_FILE_ID> [TITLE]\n"
        "  python main.py upload_and_attach <COURSE_ID> <FILE_PATH> [TITLE]\n"
    )


def _cli() -> None:
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "courses":
            list_courses()
        elif cmd == "course":
            show_course_details(sys.argv[2])
        elif cmd == "students":
            list_students(sys.argv[2])
        elif cmd == "coursework":
            list_coursework(sys.argv[2])
        elif cmd == "materials":
            list_materials(sys.argv[2])
        elif cmd == "upload":
            file_id = upload_file_to_drive(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
            print(file_id)
        elif cmd == "attach":
            course_id, file_id = sys.argv[2], sys.argv[3]
            title = sys.argv[4] if len(sys.argv) > 4 else None
            post_material_to_class(course_id, file_id, title)
        elif cmd == "upload_and_attach":
            course_id, file_path = sys.argv[2], sys.argv[3]
            title = sys.argv[4] if len(sys.argv) > 4 else None
            file_id = upload_file_to_drive(file_path)
            post_material_to_class(course_id, file_id, title)
        else:
            usage()
            sys.exit(1)

    except HttpError as exc:
        print(f"HTTP error: {exc}")
        if exc.resp is not None:
            print(f"Status: {exc.resp.status}")
        if exc.content:
            try:
                print(json.dumps(json.loads(exc.content.decode()), indent=2))
            except Exception:
                pass
        sys.exit(2)


if __name__ == "__main__":
    _cli()
