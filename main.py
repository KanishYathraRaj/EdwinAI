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
CORS(app)

genai_client = genai.Client()
embedder = SentenceTransformer("all-MiniLM-L6-v2")
chroma_client = chromadb.PersistentClient(path="./chromaDB")
chroma_collection = chroma_client.get_or_create_collection(name="my_collection")


@app.route("/ask", methods=["POST"])
def ask_route():
    return llm.ask(genai_client, request, chroma_collection, db)

@app.route("/generate_question_bank", methods=["POST"])
def generate_question_bank_route():
    return llm.generate_question_bank(genai_client, request, chroma_collection, db)

@app.route("/generate_documentation", methods=["POST"])
def generate_documentation_route():
    return llm.generate_documentation(genai_client, request, chroma_collection, db)

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

if __name__ == "__main__":
    app.run(debug=True)

