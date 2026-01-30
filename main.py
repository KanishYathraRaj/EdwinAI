from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
import json
import os
import logging
import chromadb
from sentence_transformers import SentenceTransformer

import syllabus
import resources
import llm
import firebase
import download
import llm_provider
db = firebase.db

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
# Enhanced CORS configuration to handle Cloud Workstations and all origins
CORS(
    app,
    resources={r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": "*",
        "expose_headers": "*",
        "supports_credentials": True,
    }},
    supports_credentials=True,
    allow_headers="*",
    expose_headers="*",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)

llm_client = llm_provider.get_llm_client()
embedder = SentenceTransformer("all-MiniLM-L6-v2")
chroma_client = chromadb.PersistentClient(path="./chromaDB")
chroma_collection = chroma_client.get_or_create_collection(name="my_collection")


@app.after_request
def after_request(response):
    """Ensure CORS headers are always set."""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response


@app.route("/", methods=["GET"])
def root():
    """Root endpoint with API information."""
    return jsonify({
        "message": "EdwinAI API Server",
        "status": "running",
        "endpoints": {
            "ask": "POST /ask",
            "generate_question_bank": "POST /generate_question_bank",
            "generate_documentation": "POST /generate_documentation",
            "generate_assessment": "POST /generate_assessment",
            "download_question_bank": "POST /download_question_bank",
            "upsert_syllabus": "POST /upsert_syllabus",
            "upsert_resources": "POST /upsert_resources",
            "gcr_courses": "GET /gcr/courses",
            "gcr_students": "GET /gcr/courses/<course_id>/students",
        }
    })


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    """Handle favicon requests."""
    return "", 204  # No Content


@app.route("/ask", methods=["POST"])
def ask_route():
    return llm.ask(llm_client, request, chroma_collection, db)

@app.route("/generate_question_bank", methods=["POST"])
def generate_question_bank_route():
    return llm.generate_question_bank(llm_client, request, chroma_collection, db)

@app.route("/generate_documentation", methods=["POST"])
def generate_documentation_route():
    return llm.generate_documentation(llm_client, request, chroma_collection, db)

@app.route("/generate_assessment", methods=["POST"])
def generate_assessment_route():
    return llm.generate_assessment(llm_client, request, chroma_collection, db)

@app.route("/download_question_bank", methods=["POST"])
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

@app.route("/upsert_syllabus", methods=["POST"])
def upsert_syllabus_route():
    return syllabus.upsert_syllabus(llm_client, request, db)

@app.route("/upsert_resources", methods=["POST"])
def upsert_resources_route():
    return resources.upsert_resources(request, chroma_collection, embedder, db)

from gcr_integration import register_gcr_routes
register_gcr_routes(app)

if __name__ == "__main__":
    app.run(debug=True)
