from utils import extract_text_from_pdf
import os
import json
import logging
from flask import jsonify

logger = logging.getLogger(__name__)

def upsert_syllabus(client, request, db):
    try:
        user_id = request.form.get("user_id")
        subject_id = request.form.get("subject_id")

        print(user_id)
        print(subject_id)

        # Check if a file was uploaded
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        # file = request.form.get("file")
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Save file temporarily
        pdf_path = os.path.join("data", file.filename)
        os.makedirs("data", exist_ok=True)
        file.save(pdf_path)

        # Extract text from PDF
        pdf_text = extract_text_from_pdf(pdf_path)

        # Prepare prompt
        prompt = f"""
        You are an assistant that extracts only the syllabus topics and subtopics from a document.

        Here is the text extracted from a syllabus PDF:
        ---
        {pdf_text}
        ---

        Please:
        1. Ignore non-syllabus text like page numbers, headers, or footers.
        2. Identify course title, units, and topics.
        3. Return the result strictly in JSON format:
        {{
          "course_title": "",
          "units": [
            {{
              "unit_number": "",
              "unit_title": "",
              "topics": ["", "", ""]
            }}
          ]
        }}
        """

        # Send to Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",  # use gemini-2.0-flash if available
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )

        raw = response.text

        # Handle possible double-encoded JSON
        try:
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
        except Exception:
            return jsonify({"error": "Failed to parse JSON from Gemini", "raw_output": raw}), 500

        # Save JSON file (optional)
        json_path = pdf_path.replace(".pdf", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        # Save to Firebase
        try:
            db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
                .set({"syllabus": data}, merge=True)
        except Exception as e:
            logger.exception("Firestore write failed in /upsert_syllabus: %s", e)

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
