from utils import extract_text_from_pdf
import os
import json
import logging
from flask import jsonify

logger = logging.getLogger(__name__)


def _normalize_duration_minutes(value, default_minutes=60):
    try:
        if isinstance(value, str):
            cleaned = "".join(ch for ch in value if ch.isdigit())
            value = int(cleaned) if cleaned else default_minutes
        minutes = int(value)
    except Exception:
        minutes = default_minutes
    # Keep sane bounds for one topic estimate.
    return max(15, min(360, minutes))


def _normalize_syllabus_schema(data, default_title="Centralized Syllabus"):
    if not isinstance(data, dict):
        data = {}
    course_title = data.get("course_title") or default_title
    units_in = data.get("units", []) if isinstance(data.get("units", []), list) else []
    units_out = []

    for idx, unit in enumerate(units_in):
        if not isinstance(unit, dict):
            continue
        topics_in = unit.get("topics", []) if isinstance(unit.get("topics", []), list) else []
        topics_out = []
        for t_idx, topic in enumerate(topics_in):
            if not isinstance(topic, dict):
                continue
            title = (topic.get("title") or topic.get("topic_title") or f"Topic {t_idx + 1}").strip()
            subtopics = topic.get("subtopics", topic.get("sub_topics", [])) or []
            if not isinstance(subtopics, list):
                subtopics = []
            clean_subtopics = [s.strip() for s in subtopics if isinstance(s, str) and s.strip()]
            estimated_minutes = _normalize_duration_minutes(
                topic.get("estimated_minutes", topic.get("duration_minutes", 60)),
                default_minutes=max(45, min(180, max(1, len(clean_subtopics)) * 20)),
            )
            topics_out.append({
                "title": title,
                "subtopics": clean_subtopics,
                "estimated_minutes": estimated_minutes,
            })
        units_out.append({
            "unit_number": unit.get("unit_number") or f"Unit {idx + 1}",
            "unit_title": unit.get("unit_title") or f"Unit {idx + 1}",
            "topics": topics_out,
        })

    if not units_out:
        units_out = [{
            "unit_number": "Unit 1",
            "unit_title": "Core Topics",
            "topics": []
        }]

    return {"course_title": course_title, "units": units_out}


def _heuristic_syllabus_from_text(text):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    course_title = lines[0] if lines else "Course Syllabus"
    unit = {"unit_number": "Unit 1", "unit_title": "Core Topics", "topics": []}
    seen = set()

    for ln in lines:
        cleaned = ln.strip(" -*•\t")
        if len(cleaned) < 4:
            continue
        if cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        unit["topics"].append({"title": cleaned[:120], "subtopics": [], "estimated_minutes": 60})
        if len(unit["topics"]) >= 25:
            break

    return _normalize_syllabus_schema({
        "course_title": course_title,
        "units": [unit],
    }, default_title=course_title)

def _load_json_response(raw):
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        return data
    except Exception:
        return None


def _fallback_merge_syllabus(existing, incoming):
    existing = existing or {}
    incoming = incoming or {}

    merged = {
        "course_title": incoming.get("course_title") or existing.get("course_title") or "Centralized Syllabus",
        "units": [],
    }

    unit_index = {}
    for unit in existing.get("units", []) + incoming.get("units", []):
        unit_key = (unit.get("unit_number") or "").strip().lower() or (unit.get("unit_title") or "").strip().lower()
        if not unit_key:
            unit_key = f"unit-{len(unit_index)+1}"

        if unit_key not in unit_index:
            unit_index[unit_key] = {
                "unit_number": unit.get("unit_number", f"Unit {len(unit_index)+1}"),
                "unit_title": unit.get("unit_title", "Untitled Unit"),
                "topics": [],
            }
            merged["units"].append(unit_index[unit_key])

        merged_unit = unit_index[unit_key]
        topic_index = {
            (t.get("title") or "").strip().lower(): t
            for t in merged_unit.get("topics", [])
            if isinstance(t, dict)
        }

        for topic in unit.get("topics", []):
            title = (topic.get("title") or "").strip() or "Untitled Topic"
            topic_key = title.lower()
            subtopics = topic.get("subtopics", []) or []
            estimated_minutes = _normalize_duration_minutes(
                topic.get("estimated_minutes", topic.get("duration_minutes", 60)),
                default_minutes=max(45, min(180, max(1, len(subtopics)) * 20)),
            )

            if topic_key not in topic_index:
                normalized = {
                    "title": title,
                    "subtopics": [],
                    "estimated_minutes": estimated_minutes,
                }
                for subtopic in subtopics:
                    if isinstance(subtopic, str) and subtopic.strip() and subtopic.strip() not in normalized["subtopics"]:
                        normalized["subtopics"].append(subtopic.strip())
                merged_unit["topics"].append(normalized)
                topic_index[topic_key] = normalized
            else:
                existing_topic = topic_index[topic_key]
                existing_topic["estimated_minutes"] = _normalize_duration_minutes(
                    max(
                        int(existing_topic.get("estimated_minutes") or 0),
                        estimated_minutes,
                    ),
                    default_minutes=estimated_minutes,
                )
                for subtopic in subtopics:
                    if isinstance(subtopic, str):
                        st = subtopic.strip()
                        if st and st not in existing_topic["subtopics"]:
                            existing_topic["subtopics"].append(st)

    return merged


def _extract_syllabus_from_text(client, text):
    prompt = f"""
    You are an expert academic assistant specializing in syllabus parsing.
    Extract the course structure from the provided text into a highly structured nested JSON.
    
    Rules:
    1. Identify the Course Title.
    2. Group content into Units/Modules.
    3. For each Unit, identify main Topics.
    4. For each Topic, identify Sub-topics (if any).
    5. MAX DENSITY: Ensure topics and sub-topics are granular. If a topic is too broad, break it down. Aim for 3-7 sub-topics per main topic to provide a detailed learning path.
    6. IGNORE: Page numbers, faculty names, office hours, grading policies, or administrative text.
    
    JSON Structure:
    {{
      "course_title": "Full Name of Course",
      "units": [
        {{
          "unit_number": "Unit 1",
          "unit_title": "Title of Unit",
          "topics": [
            {{
              "title": "Main Topic Name",
              "subtopics": ["Subtopic A", "Subtopic B"],
              "estimated_minutes": 90
            }}
          ]
        }}
      ]
    }}

    Extracted Text:
    ---
    {text}
    ---
    """
    try:
        raw = client.generate(prompt, response_mime_type="application/json")
        parsed = _load_json_response(raw)
        if parsed is None:
            return _heuristic_syllabus_from_text(text)
        return _normalize_syllabus_schema(parsed)
    except Exception:
        logger.exception("LLM syllabus extraction failed; using heuristic fallback")
        return _heuristic_syllabus_from_text(text)


def _merge_syllabus_with_existing(client, existing_syllabus, incoming_syllabus):
    existing_syllabus = _normalize_syllabus_schema(existing_syllabus or {})
    incoming_syllabus = _normalize_syllabus_schema(incoming_syllabus or {})
    if not existing_syllabus or not existing_syllabus.get("units"):
        return incoming_syllabus

    prompt = f"""
    You are merging two syllabus JSON documents into one centralized syllabus.
    Return JSON only.

    Rules:
    1. Keep all unique units/topics/subtopics from both inputs.
    2. Deduplicate semantically similar topics/subtopics.
    3. Preserve clear unit ordering and topic ordering.
    4. Keep the same output schema:
    {{
      "course_title": "string",
      "units": [
        {{
          "unit_number": "string",
          "unit_title": "string",
          "topics": [
            {{
              "title": "string",
              "subtopics": ["string"],
              "estimated_minutes": 90
            }}
          ]
        }}
      ]
    }}

    Existing Syllabus JSON:
    {json.dumps(existing_syllabus, indent=2)}

    New Syllabus JSON:
    {json.dumps(incoming_syllabus, indent=2)}
    """
    raw = client.generate(prompt, response_mime_type="application/json")
    merged = _load_json_response(raw)
    if merged is None:
        return _fallback_merge_syllabus(existing_syllabus, incoming_syllabus)
    return _normalize_syllabus_schema(merged)


def build_centralized_syllabus(client, extracted_text, existing_syllabus=None):
    incoming = _extract_syllabus_from_text(client, extracted_text)
    merged = _merge_syllabus_with_existing(client, existing_syllabus or {}, incoming)
    return _normalize_syllabus_schema(merged)


def _resolve_subject_doc_ref(db, user_id, subject_id=None, subject_slug=None):
    subjects_ref = db.collection("users").document(user_id).collection("subjects")
    if subject_id:
        doc_ref = subjects_ref.document(subject_id)
        snap = doc_ref.get()
        if snap.exists:
            return doc_ref, snap
    if subject_slug:
        query = subjects_ref.where("slug", "==", subject_slug).limit(1).get()
        if query:
            snap = query[0]
            return snap.reference, snap
    return None, None


def _extract_text_for_file(path):
    _, ext = os.path.splitext(path.lower())
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    if ext in {".txt", ".md"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return ""


def _collect_subject_documents_text(subject_data):
    documents = subject_data.get("documents", []) or []
    resources = subject_data.get("resources", []) or []

    candidate_names = []
    for d in documents:
        name = d.get("title") if isinstance(d, dict) else None
        if isinstance(name, str) and name.strip():
            candidate_names.append(name.strip())
    for r in resources:
        if isinstance(r, str) and r.strip():
            candidate_names.append(r.strip())

    seen = set()
    text_blocks = []
    used_files = []
    missing_files = []
    skipped_files = []

    for name in candidate_names:
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join("data", name)
        if not os.path.exists(path):
            missing_files.append(name)
            continue
        extracted = _extract_text_for_file(path)
        if extracted and extracted.strip():
            text_blocks.append(f"\n\n=== DOCUMENT: {name} ===\n{extracted}\n")
            used_files.append(name)
        else:
            skipped_files.append(name)

    return {
        "combined_text": "\n".join(text_blocks).strip(),
        "used_files": used_files,
        "missing_files": missing_files,
        "skipped_files": skipped_files,
    }


def upsert_syllabus(client, request, db):
    try:
        user_id = request.form.get("user_id")
        subject_id = request.form.get("subject_id")
        subject_slug = request.form.get("subject_slug")

        # Check if a file was uploaded
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        # file = request.form.get("file")
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Save file temporarily
        file_path = os.path.join("data", file.filename)
        os.makedirs("data", exist_ok=True)
        file.save(file_path)

        extracted_text = _extract_text_for_file(file_path)
        if not extracted_text or not extracted_text.strip():
            return jsonify({"error": "Could not extract text from uploaded file"}), 400

        if not user_id or (not subject_id and not subject_slug):
            return jsonify({"error": "Missing user_id and subject identifier (subject_id or subject_slug)"}), 400

        subject_ref, subject_snap = _resolve_subject_doc_ref(db, user_id, subject_id, subject_slug)
        if not subject_ref or not subject_snap:
            return jsonify({"error": "Subject not found"}), 404

        existing_syllabus = {}
        try:
            if subject_snap.exists:
                existing_syllabus = (subject_snap.to_dict() or {}).get("syllabus", {}) or {}
        except Exception:
            existing_syllabus = {}

        if existing_syllabus and existing_syllabus.get("units"):
            return jsonify({"error": "Syllabus already exists for this subject and cannot be replaced"}), 409

        data = build_centralized_syllabus(client, extracted_text, existing_syllabus)

        # Save JSON file (optional)
        stem, _ = os.path.splitext(file_path)
        json_path = f"{stem}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        # Save to Firebase
        try:
            subject_ref.set({"syllabus": data, "syllabus_status": "ready"}, merge=True)
        except Exception as e:
            logger.exception("Firestore write failed in /upsert_syllabus: %s", e)

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def reprocess_syllabus(client, request, db):
    try:
        return jsonify({
            "error": "Syllabus reprocessing is disabled. Upload syllabus only during subject creation."
        }), 410

    except Exception as e:
        logger.exception("Error in /reprocess_syllabus")
        return jsonify({"error": str(e)}), 500
