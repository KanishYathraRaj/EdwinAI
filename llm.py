from flask import request, jsonify
import json
import re
import logging
from firebase_admin import firestore
from google.api_core.exceptions import ResourceExhausted
from google.auth.exceptions import RefreshError
from urllib.error import URLError


logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("No JSON structure found in LLM output")
    raw = match.group(0)
    # Balance braces/brackets if the model truncated output.
    open_curly = raw.count("{")
    close_curly = raw.count("}")
    if close_curly < open_curly:
        raw += "}" * (open_curly - close_curly)
    open_brack = raw.count("[")
    close_brack = raw.count("]")
    if close_brack < open_brack:
        raw += "]" * (open_brack - close_brack)
    return raw


def _safe_json_loads(raw: str):
    # Try direct parse first.
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Heuristic cleanup: strip code fences, trim to outer JSON, remove trailing commas.
    trimmed = _extract_json(raw)
    # Insert missing comma before answer_key_plan if needed.
    trimmed = re.sub(r"(\]|\})\s*\n\s*\"answer_key_plan\"", r"\1,\n  \"answer_key_plan\"", trimmed)
    trimmed = re.sub(r",\s*([}\]])", r"\1", trimmed)
    try:
        return json.loads(trimmed)
    except Exception:
        pass

    # Fallback: extract fragments for requests + answer_key_plan and rebuild.
    def _clean_fragment(text: str) -> str:
        text = text.strip()
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text

    req_match = re.search(r"\"requests\"\s*:\s*(\[[\s\S]*?\])", trimmed)
    ak_match = re.search(r"\"answer_key_plan\"\s*:\s*(\{[\s\S]*\})", trimmed)
    if req_match and ak_match:
        requests_fragment = _clean_fragment(req_match.group(1))
        answer_fragment = _clean_fragment(ak_match.group(1))
        return {
            "requests": json.loads(requests_fragment),
            "answer_key_plan": json.loads(answer_fragment),
        }

    raise ValueError("Failed to parse JSON from LLM output")


def _error_response(exc: Exception):
    msg = str(exc)
    logger.exception("LLM request failed: %s", msg)
    if isinstance(exc, TimeoutError) or isinstance(exc, URLError):
        return jsonify({
            "error": msg,
            "code": "LLM_TIMEOUT",
            "hint": "LLM provider timed out. Check Ollama is running and consider increasing OLLAMA_TIMEOUT_SECONDS.",
        }), 504
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

        ai_reply = client.generate(prompt)

        try:
            db.collection("users").document(user_id) \
                .collection("subjects").document(subject_id) \
                .set({"conversation_history": firestore.ArrayUnion([
                    {"role": "user", "content": user_query},
                    {"role": "assistant", "content": ai_reply}
                ])}, merge=True)
        except Exception as e:
            logger.exception("Firestore write failed in /ask: %s", e)

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

        raw = client.generate(prompt)

        try:
            data_out = _safe_json_loads(raw)
        except Exception as e:
            return jsonify({"error": str(e), "raw_output": raw}), 500
        if isinstance(data_out, str):
            data_out = json.loads(data_out)

        try:
            db.collection("users").document(user_id).collection("subjects").document(subject_id).set(
                {"question_bank": data_out}, merge=True
            )
        except Exception as e:
            logger.exception("Firestore write failed in /generate_question_bank: %s", e)

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
Generate a Google Forms API v1 forms.batchUpdate body content with ONLY these fields:
- updateSettings.settings.quizSettings.isQuiz
- updateSettings.updateMask
- createItem.location.index
- createItem.item.title
- createItem.item.questionItem.question.required
- createItem.item.questionItem.question.textQuestion.paragraph
- createItem.item.questionItem.question.choiceQuestion.type
- createItem.item.questionItem.question.choiceQuestion.options[].value
- createItem.item.questionItem.question.choiceQuestion.shuffle
- createItem.item.questionItem.question.grading.pointValue
- createItem.item.questionItem.question.grading.correctAnswers.answers[].value
- createItem.item.questionItem.question.whenRight.text
- createItem.item.questionItem.question.whenWrong.text

STRICT RULES:
- Do NOT invent fields (e.g., "generalAnswerKey" or any unknown keys).
- Use only keys listed above; any extra key is invalid.
- Return valid JSON with double quotes and NO trailing commas.
- No code fences, no prose.

Tasks:
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
- question.choiceQuestion.options = [{{"value":"A"}},{{"value":"B"}},{{"value":"C"}},{{"value":"D"}}]
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

        raw = client.generate(prompt)

        try:
            llm_obj = _safe_json_loads(raw)
        except Exception as e:
            return jsonify({"error": str(e), "raw_output": raw}), 500
        requests_payload = llm_obj.get("requests")
        answer_key_plan = llm_obj.get("answer_key_plan") or {}

        if not isinstance(requests_payload, list) or not requests_payload:
            return jsonify({"error": "LLM output must contain non-empty 'requests' list", "raw_output": raw}), 500

        # Normalize malformed question payloads from the LLM to match Forms API schema.
        for req in requests_payload:
            # Normalize common snake_case keys to camelCase.
            if "create_item" in req and "createItem" not in req:
                req["createItem"] = req.pop("create_item")
            if "update_settings" in req and "updateSettings" not in req:
                req["updateSettings"] = req.pop("update_settings")

            create_item = (req or {}).get("createItem") or {}
            item = create_item.get("item") or {}
            if "question_item" in item and "questionItem" not in item:
                item["questionItem"] = item.pop("question_item")
            qitem = item.get("questionItem") or {}
            question = qitem.get("question")
            if not isinstance(question, dict):
                continue

            if "choice_question" in question and "choiceQuestion" not in question:
                question["choiceQuestion"] = question.pop("choice_question")

            # Fix common mistake: feedback placed directly on question.
            when_right = question.pop("whenRight", None)
            when_wrong = question.pop("whenWrong", None)
            if when_right or when_wrong:
                q_grading = question.get("grading") or {}
                if isinstance(when_right, dict):
                    q_grading["whenRight"] = when_right
                if isinstance(when_wrong, dict):
                    q_grading["whenWrong"] = when_wrong
                question["grading"] = q_grading

            # Fix common mistake: grading/feedback placed under choiceQuestion.
            choice = question.get("choiceQuestion")
            if isinstance(choice, dict):
                grading = choice.pop("grading", None)
                when_right = choice.pop("whenRight", None)
                when_wrong = choice.pop("whenWrong", None)
                if grading or when_right or when_wrong:
                    q_grading = question.get("grading") or {}
                    if isinstance(grading, dict):
                        q_grading.update(grading)
                    if isinstance(when_right, dict):
                        q_grading["whenRight"] = when_right
                    if isinstance(when_wrong, dict):
                        q_grading["whenWrong"] = when_wrong
                    question["grading"] = q_grading

            # Drop any invalid keys accidentally placed on questionItem.
            for bad_key in ("generalAnswerKey", "answerKey", "general_answer_key"):
                qitem.pop(bad_key, None)

        mcq_plan = answer_key_plan.get("mcq")
        if not isinstance(mcq_plan, list) or len(mcq_plan) != num_questions:
            # Try to recover from malformed LLM output by deriving from requests.
            derived = []
            for req in requests_payload:
                create_item = (req or {}).get("createItem") or {}
                item = create_item.get("item") or {}
                qitem = item.get("questionItem") or {}
                question = qitem.get("question") or {}
                choice = question.get("choiceQuestion") or {}
                grading = question.get("grading") or {}
                correct = ((grading.get("correctAnswers") or {}).get("answers") or [{}])
                if not choice:
                    continue
                correct_val = (correct[0] or {}).get("value")
                if correct_val is None:
                    continue
                derived.append(
                    {"mcq_index": len(derived), "correct": correct_val, "points": int(grading.get("pointValue", points_per_question))}
                )

            if len(derived) == 0:
                return jsonify({
                    "error": "answer_key_plan.mcq must be a list of length num_questions",
                    "raw_output": raw,
                }), 500

            mcq_plan = derived

        mcq_count = len(mcq_plan)
        if mcq_count != num_questions:
            logger.warning(
                "LLM returned %s MCQs but request asked for %s; continuing with %s",
                mcq_count,
                num_questions,
                mcq_count,
            )

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
        if len(mcq_question_ids) != mcq_count:
            return jsonify({"error": "MCQ count mismatch after batchUpdate", "got": len(mcq_question_ids), "expected": mcq_count}), 500

        # Build answer_key dict keyed by questionId
        # answer_key[questionId] = { correct: "...", points: N }
        answer_key = {}
        # validate indices
        idxs = sorted(int(x.get("mcq_index", -1)) for x in mcq_plan if isinstance(x, dict))
        if idxs != list(range(mcq_count)):
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

        max_points = mcq_count * points_per_question

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
            try:
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
            except Exception as e:
                logger.exception("Firestore write failed in /generate_assessment: %s", e)

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

        raw = client.generate(prompt)

        try:
            data_out = _safe_json_loads(raw)
        except Exception as e:
            return jsonify({"error": str(e), "raw_output": raw}), 500
        if isinstance(data_out, str):
            data_out = json.loads(data_out)

        try:
            db.collection("users").document(user_id).collection("subjects").document(subject_id).set(
                {"documentation": data_out}, merge=True
            )
        except Exception as e:
            logger.exception("Firestore write failed in /generate_documentation: %s", e)

        return jsonify({"reply": data_out})

    except Exception as e:
        return _error_response(e)
