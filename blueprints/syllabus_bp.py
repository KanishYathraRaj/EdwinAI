import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, current_app
import syllabus

syllabus_bp = Blueprint('syllabus', __name__)

@syllabus_bp.route("/upsert_syllabus", methods=["POST"])
def upsert_syllabus_route():
    llm_client = current_app.config['LLM_CLIENT']
    db = current_app.config['FIREBASE_DB']
    return syllabus.upsert_syllabus(llm_client, request, db)
