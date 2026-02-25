import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, current_app, send_file, jsonify
import llm
import download
import json

llm_bp = Blueprint('llm', __name__)

@llm_bp.route("/ask", methods=["POST"])
def ask_route():
    llm_client = current_app.config['LLM_CLIENT']
    chroma_collection = current_app.config['CHROMA_COLLECTION']
    db = current_app.config['FIREBASE_DB']
    return llm.ask(llm_client, request, chroma_collection, db)

@llm_bp.route("/generate_question_bank", methods=["POST"])
def generate_question_bank_route():
    llm_client = current_app.config['LLM_CLIENT']
    chroma_collection = current_app.config['CHROMA_COLLECTION']
    db = current_app.config['FIREBASE_DB']
    return llm.generate_question_bank(llm_client, request, chroma_collection, db)

@llm_bp.route("/generate_documentation", methods=["POST"])
def generate_documentation_route():
    llm_client = current_app.config['LLM_CLIENT']
    chroma_collection = current_app.config['CHROMA_COLLECTION']
    db = current_app.config['FIREBASE_DB']
    return llm.generate_documentation(llm_client, request, chroma_collection, db)

@llm_bp.route("/generate_assessment", methods=["POST"])
def generate_assessment_route():
    llm_client = current_app.config['LLM_CLIENT']
    chroma_collection = current_app.config['CHROMA_COLLECTION']
    db = current_app.config['FIREBASE_DB']
    return llm.generate_assessment(llm_client, request, chroma_collection, db)

@llm_bp.route("/download_question_bank", methods=["POST"])
def generate_pdf():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        pdf_buffer = download.question_bank_to_pdf(data)
        filename = data.get("course_title", "question_bank").replace(" ", "_") + ".pdf"

        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
