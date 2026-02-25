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
                  "subtopics": ["Subtopic A", "Subtopic B"]
                }}
              ]
            }}
          ]
        }}

        Extracted Text:
        ---
        {pdf_text}
        ---
        """

        # Send to Gemini
        raw = client.generate(prompt, response_mime_type="application/json")

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
