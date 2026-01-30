from flask import request, jsonify
import json
import re
from firebase_admin import firestore
from google.api_core.exceptions import ResourceExhausted
from google.auth.exceptions import RefreshError


def _error_response(exc: Exception):
    msg = str(exc)
    if isinstance(exc, RefreshError) or "invalid_grant" in msg.lower():
        return jsonify({
            "error": msg,
            "code": "INVALID_GRANT",
            "hint": "OAuth token is invalid/expired. Delete token.json and re-auth via /gcr/auth or run gcr_client.py.",
        }), 401
    if isinstance(exc, ResourceExhausted) or "RESOURCE_EXHAUSTED" in msg:
        return jsonify({"error": msg, "code": "RESOURCE_EXHAUSTED"}), 429
    return jsonify({"error": msg}), 500


def ask(client, request, collection, db):
    try:
        data = request.get_json()

        user_query = data.get("user_query")
        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})
        grounded = data.get("grounded")

        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])
        conversation_history = user_subject_json.get("conversation_history", [])

        grounded_text = ""
        if grounded is False:
            grounded_text = "if the retrived study material is empty then generate based on your current level of knowledge"

        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[user_query],
                    n_results=5,
                    where={"resources": {"$in": resources}}
                )
                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
            except Exception:
                rag_context = ""

        context = f"""
Subject: {subject_name}
Course Title: {syllabus.get('course_title', '')}
Units:
{json.dumps(syllabus.get('units', []), indent=2)}
Resources (metadata filters): {', '.join(resources)}
Previous Conversation:
{json.dumps(conversation_history[-10:], indent=2)}
Retrieved Study Material from ChromaDB:
{rag_context}
{grounded_text}
"""

        prompt = f"""
You are an intelligent teaching assistant.
Use the syllabus, resources, and retrieved content below to answer precisely.
don't add markdown styles in the generated content

Context:
{context}

Question: {user_query}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )

        ai_reply = response.text.strip()

        db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
            .set({"conversation_history": firestore.ArrayUnion([
                {"role": "user", "message": user_query},
                {"role": "system", "message": ai_reply}
            ])}, merge=True)

        return jsonify({
            "reply": ai_reply,
            "user_id": user_id,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "rag_context": rag_context,
            "syllabus": syllabus,
            "conversation_history": conversation_history
        })

    except Exception as e:
        return _error_response(e)


def generate_question_bank(client, request, collection, db):
    try:
        data = request.get_json()

        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})

        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])

        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[json.dumps(syllabus, indent=2)],
                    n_results=5,
                    where={"resource": {"$in": resources}}
                )
                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
            except Exception:
                rag_context = ""

        prompt = f"""
You are a university-level teaching assistant and question bank generator.

Subject: {subject_name}
Syllabus: {json.dumps(syllabus, indent=2)}
Retrieved Study Material: {rag_context}

Return JSON only:
{{
  "course_title": "",
  "units": [
    {{
      "unit_number": "",
      "unit_title": "",
      "2_marks": ["", ""],
      "16_marks": ["", ""]
    }}
  ]
}}
"""

        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        raw = response.text.strip()

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return jsonify({"error": "No JSON structure found in Gemini output", "raw_output": raw}), 500

        data_out = json.loads(match.group(0))
        if isinstance(data_out, str):
            data_out = json.loads(data_out)

        db.collection("users").document(user_id).collection("subjects").document(subject_id).set(
            {"question_bank": data_out}, merge=True
        )

        return jsonify({"reply": data_out})

    except Exception as e:
        return _error_response(e)


def generate_assessment(client, request, collection, db):
    """
    Workflow:
      1) Create empty Google Form
      2) LLM generates valid Forms API batchUpdate 'requests' + answer_key_plan
      3) batchUpdate with includeFormInResponse=true to extract questionIds
      4) Attach responder URL to Classroom as ASSIGNMENT LINK
      5) Store form_id + coursework_id + identifier_question_id + answer_key for refresh endpoint
    """
    try:
        data = request.get_json() or {}

        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        course_id = data.get("course_id")
        user_subject_json = data.get("user_subject_json", {})

        quiz_title = data.get("quiz_title")
        quiz_description = data.get("quiz_description", "")
        difficulty = data.get("difficulty", "medium")
        num_questions = int(data.get("num_questions", 10))
        points_per_question = int(data.get("points_per_question", 1))
        shuffle_options = bool(data.get("shuffle_options", True))
        state = data.get("state", "PUBLISHED")
        grounded = data.get("grounded", True)

        if not quiz_title:
            return jsonify({"error": "quiz_title is required"}), 400
        if not course_id:
            return jsonify({"error": "course_id is required"}), 400

        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])

        # Optional RAG
        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[quiz_title],
                    n_results=5,
                    where={"resource": {"$in": resources}}
                )
                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
            except Exception:
                rag_context = ""

        grounded_text = ""
        if grounded is False:
            grounded_text = "If retrieved study material is empty, generate based on your current level of knowledge."

        import gcr_client

        # 1) Create empty form
        created_form = gcr_client.create_form(quiz_title)
        form_id = created_form.get("formId")
        if not form_id:
            return jsonify({"error": "Failed to create form (no formId)"}), 500

        # 2) Prompt LLM for VALID Forms API batchUpdate payload
        # IMPORTANT: Use the exact schema names used by Forms API (camelCase).
        prompt = f"""
Return ONLY valid JSON. No markdown. No commentary.

We already created an empty Google Form titled "{quiz_title}".
Generate a Google Forms API v1 forms.batchUpdate body content (ONLY the "requests" list) to:

A) Enable quiz mode
B) Add ONE first question (short answer) titled "Student email" (required=true)
C) Add EXACTLY {num_questions} multiple-choice questions (RADIO), each with exactly 4 options.
   - required=true
   - shuffle options = {str(shuffle_options).lower()}
   - grading.pointValue = {points_per_question}
   - grading.correctAnswers.answers[0].value must match one option value EXACTLY
   - add whenRight.text and whenWrong.text (short)

Use this exact structure for quiz settings:
{{
  "updateSettings": {{
    "settings": {{
      "quizSettings": {{
        "isQuiz": true
      }}
    }},
    "updateMask": "quizSettings.isQuiz"
  }}
}}

Use this exact structure for creating an item:
{{
  "createItem": {{
    "location": {{ "index": 0 }},
    "item": {{
      "title": "Question title",
      "questionItem": {{
        "question": {{
          "required": true,
          "textQuestion": {{ "paragraph": false }}
        }}
      }}
    }}
  }}
}}

For MCQ use:
- question.choiceQuestion.type = "RADIO"
- question.choiceQuestion.options = [{{"value":"A"}},...]
- question.choiceQuestion.shuffle = true/false

Return JSON with TWO keys:
1) "requests": [ ... ]
2) "answer_key_plan": {{
     "mcq": [
        {{ "mcq_index": 0, "correct": "Option text", "points": {points_per_question} }}
     ]
   }}

Rules:
- The first created question MUST be the short answer identifier.
- The MCQ order after that is mcq_index 0..{num_questions-1}.
- Keep questions strictly within the syllabus topics and avoid duplicates.

Context:
Subject: {subject_name}
Syllabus: {json.dumps(syllabus, indent=2)}
Retrieved: {rag_context}
{grounded_text}
"""

        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw = (resp.text or "").strip()

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return jsonify({"error": "No JSON found in LLM response", "raw_output": raw}), 500

        llm_obj = json.loads(match.group(0))
        requests_payload = llm_obj.get("requests")
        answer_key_plan = llm_obj.get("answer_key_plan") or {}

        if not isinstance(requests_payload, list) or not requests_payload:
            return jsonify({"error": "LLM output must contain non-empty 'requests' list", "raw_output": raw}), 500

        mcq_plan = answer_key_plan.get("mcq")
        if not isinstance(mcq_plan, list) or len(mcq_plan) != num_questions:
            return jsonify({"error": "answer_key_plan.mcq must be a list of length num_questions", "raw_output": raw}), 500

        # 3) Apply batchUpdate and include form in response to extract questionIds
        batch_resp = gcr_client.forms_batch_update_with_retries(
            form_id=form_id,
            requests_payload=requests_payload,
            max_retries=4,
            include_form_in_response=True
        )

        updated_form = (batch_resp.get("form") or {})
        items = updated_form.get("items") or []

        identifier_question_id = None
        mcq_question_ids = []

        # Extract questionIds in the order they appear
        for it in items:
            qi = it.get("questionItem") or {}
            q = qi.get("question") or {}
            qid = q.get("questionId")
            if not qid:
                continue

            # Identifier is first short answer with textQuestion
            if ("textQuestion" in q) and (identifier_question_id is None):
                identifier_question_id = qid
            elif "choiceQuestion" in q:
                mcq_question_ids.append(qid)

        if identifier_question_id is None:
            return jsonify({"error": "Identifier questionId not found after batchUpdate"}), 500
        if len(mcq_question_ids) != num_questions:
            return jsonify({"error": "MCQ count mismatch after batchUpdate", "got": len(mcq_question_ids), "expected": num_questions}), 500

        # Build answer_key dict keyed by questionId
        # answer_key[questionId] = { correct: "...", points: N }
        answer_key = {}
        # validate indices
        idxs = sorted(int(x.get("mcq_index", -1)) for x in mcq_plan if isinstance(x, dict))
        if idxs != list(range(num_questions)):
            return jsonify({"error": "mcq_index must be sequential 0..N-1", "got": idxs}), 500

        idx_to_plan = {int(x["mcq_index"]): x for x in mcq_plan}
        for i, qid in enumerate(mcq_question_ids):
            plan = idx_to_plan[i]
            answer_key[qid] = {
                "correct": plan.get("correct", ""),
                "points": int(plan.get("points", points_per_question)),
            }

        # 4) Attach to Classroom as LINK assignment (reliable)
        links = gcr_client.get_form_links(form_id)
        responder_uri = links.get("responderUri")
        if not responder_uri:
            return jsonify({"error": "Missing responderUri from form"}), 500

        max_points = num_questions * points_per_question

        coursework = gcr_client.post_quiz_assignment_link(
            course_id=course_id,
            title=quiz_title,
            url=responder_uri,
            description=quiz_description,
            state=state,
            max_points=max_points
        )

        coursework_id = coursework.get("id")

        # 5) Store metadata (needed for GET refresh endpoint)
        if user_id and subject_id:
            db.collection("users").document(user_id).collection("subjects").document(subject_id).set(
                {
                    "latest_quiz": {
                        "title": quiz_title,
                        "description": quiz_description,
                        "course_id": course_id,
                        "coursework_id": coursework_id,
                        "form_id": form_id,
                        "responder_uri": responder_uri,
                        "max_points": max_points,
                        "identifier_question_id": identifier_question_id,
                        "answer_key": answer_key,
                        "created_at": firestore.SERVER_TIMESTAMP,
                    }
                },
                merge=True
            )

        return jsonify({
            "ok": True,
            "form": links,
            "coursework": coursework,
            "meta": {
                "form_id": form_id,
                "coursework_id": coursework_id,
                "identifier_question_id": identifier_question_id,
                "answer_key": answer_key,
                "max_points": max_points
            }
        })

    except Exception as e:
        return _error_response(e)


def generate_documentation(client, request, collection, db):
    try:
        data = request.get_json()

        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})

        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])

        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[json.dumps(syllabus, indent=2)],
                    n_results=5,
                    where={"resource": {"$in": resources}}
                )
                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
            except Exception:
                rag_context = ""

        prompt = f"""
Return JSON only.

Subject: {subject_name}
Syllabus: {json.dumps(syllabus, indent=2)}
Retrieved: {rag_context}

Output format:
{{
  "course_title": "string",
  "overview": "string",
  "units": [
    {{
      "unit_number": "I",
      "unit_title": "string",
      "topics": [
        {{
          "topic_title": "string",
          "explanation": "text",
          "examples": ["e1"],
          "real_world_applications": ["a1"],
          "summary": "short"
        }}
      ],
      "unit_summary": "short"
    }}
  ],
  "final_summary": "short"
}}
"""

        response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        raw = response.text.strip()

        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return jsonify({"error": "No JSON structure found in Gemini output", "raw_output": raw}), 500

        data_out = json.loads(match.group(0))
        if isinstance(data_out, str):
            data_out = json.loads(data_out)

        db.collection("users").document(user_id).collection("subjects").document(subject_id).set(
            {"documentation": data_out}, merge=True
        )

        return jsonify({"reply": data_out})

    except Exception as e:
        return _error_response(e)
