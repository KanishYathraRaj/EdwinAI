from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
from google import genai
import json
import os
import chromadb
from sentence_transformers import SentenceTransformer

import syllabus
import resources
import llm
import firebase
import download
db = firebase.db

app = Flask(__name__)
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

# Initialize GenAI client with API key from environment
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is not set")
genai_client = genai.Client(api_key=api_key)
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
    return llm.ask(genai_client, request, chroma_collection, db)

@app.route("/generate_question_bank", methods=["POST"])
def generate_question_bank_route():
    return llm.generate_question_bank(genai_client, request, chroma_collection, db)

@app.route("/generate_documentation", methods=["POST"])
def generate_documentation_route():
    return llm.generate_documentation(genai_client, request, chroma_collection, db)

@app.route("/generate_assessment", methods=["POST"])
def generate_assessment_route():
    return llm.generate_assessment(genai_client, request, chroma_collection, db)

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
    return syllabus.upsert_syllabus(genai_client, request, db)

@app.route("/upsert_resources", methods=["POST"])
def upsert_resources_route():
    return resources.upsert_resources(request, chroma_collection, embedder, db)

from gcr_integration import register_gcr_routes
register_gcr_routes(app)

if __name__ == "__main__":
    app.run(debug=True)

