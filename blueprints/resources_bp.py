import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Blueprint, request, current_app
import resources

resources_bp = Blueprint('resources', __name__)

@resources_bp.route("/upsert_resources", methods=["POST"])
def upsert_resources_route():
    chroma_collection = current_app.config['CHROMA_COLLECTION']
    embedder = current_app.config['EMBEDDER']
    db = current_app.config['FIREBASE_DB']
    llm_client = current_app.config['LLM_CLIENT']
    return resources.upsert_resources(request, chroma_collection, embedder, db, llm_client)
