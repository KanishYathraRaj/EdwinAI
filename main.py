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
logger = logging.getLogger(__name__)
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

import time
@app.before_request
def start_timer():
    request.start_time = time.time()
    logger.info("Request started: %s %s", request.method, request.path)

@app.after_request
def log_request(response):
    if hasattr(request, 'start_time'):
        duration = time.time() - request.start_time
        logger.info("Request finished: %s %s, Duration: %.2fs, Status: %s", 
                    request.method, request.path, duration, response.status)
    return response

llm_client = llm_provider.get_llm_client()
embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
chroma_client = chromadb.PersistentClient(path="./chromaDB")
chroma_collection = chroma_client.get_or_create_collection(name="my_collection")

# Store shared dependencies in app.config for blueprints to access
app.config['LLM_CLIENT'] = llm_client
app.config['CHROMA_COLLECTION'] = chroma_collection
app.config['FIREBASE_DB'] = db
app.config['EMBEDDER'] = embedder

# Register Blueprints
from blueprints.llm_bp import llm_bp
from blueprints.syllabus_bp import syllabus_bp
from blueprints.resources_bp import resources_bp
from gcr_integration import gcr_bp

app.register_blueprint(llm_bp)
app.register_blueprint(syllabus_bp)
app.register_blueprint(resources_bp)
app.register_blueprint(gcr_bp)


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
            "llm": ["/ask", "/generate_question_bank", "/generate_documentation", "/generate_assessment", "/download_question_bank"],
            "syllabus": ["/upsert_syllabus"],
            "resources": ["/upsert_resources"],
            "gcr": ["/gcr/auth", "/gcr/courses", "/gcr/courses/<id>/students", "..."],
        }
    })


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    """Handle favicon requests."""
    return "", 204  # No Content

if __name__ == "__main__":
    app.run(debug=True, port=5005, use_reloader=False)
