from utils import extract_text_from_pdf, chunk_text
from firebase_admin import firestore
from flask import jsonify, request as flask_request
import os
import logging
import syllabus as syllabus_service

logger = logging.getLogger(__name__)

def _resolve_subject_doc_ref(db, user_id, subject_id=None, subject_slug=None):
    subjects_ref = db.collection("users").document(user_id).collection("subjects")
    if subject_id:
        doc_ref = subjects_ref.document(subject_id)
        snap = doc_ref.get()
        if snap.exists:
            return doc_ref, snap
    if subject_slug:
        query = subjects_ref.where("slug", "==", subject_slug).limit(1).get()
        if query:
            snap = query[0]
            return snap.reference, snap
    return None, None

def upsert_resources(request, chroma_collection, embedder, db, llm_client=None):
    try:

        user_id = request.form.get("user_id")
        subject_id = request.form.get("subject_id")
        subject_slug = request.form.get("subject_slug")
        if not user_id or (not subject_id and not subject_slug):
            return jsonify({"error": "Missing user_id and subject identifier (subject_id or subject_slug)"}), 400

        subject_ref, subject_doc = _resolve_subject_doc_ref(db, user_id, subject_id, subject_slug)
        if not subject_ref or not subject_doc:
            return jsonify({"error": "Subject not found"}), 404
        # Allow the user to upload a PDF via POST
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Save file temporarily
        os.makedirs("data", exist_ok=True)
        pdf_path = os.path.join("data", file.filename)
        file.save(pdf_path)

        # Extract text and chunk
        book_text = extract_text_from_pdf(pdf_path)
        chunks = chunk_text(book_text)

        # Create embeddings
        embeddings = embedder.encode(chunks).tolist()

        print("No of chunks : ", len(chunks))

        # Store in Chroma
        ids = [f"{file.filename}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"resources" : file.filename} for i in range(len(chunks))]
        chroma_collection.upsert(
            documents=chunks,
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas
        )

        try:
            subject_ref.set({"resources": firestore.ArrayUnion([
                    file.filename
                ])}, merge=True)
        except Exception as e:
            logger.exception("Firestore write failed in /upsert_resources: %s", e)

        # Keep syllabus centralized even when user uploads via Resources flow.
        if llm_client and file.filename.lower().endswith(".pdf"):
            try:
                existing_syllabus = {}
                if subject_doc.exists:
                    existing_syllabus = (subject_doc.to_dict() or {}).get("syllabus", {}) or {}
                merged_syllabus = syllabus_service.build_centralized_syllabus(llm_client, book_text, existing_syllabus)
                subject_ref.set({"syllabus": merged_syllabus}, merge=True)
            except Exception:
                logger.exception("Syllabus merge failed during /upsert_resources")
        
        print("Stored the Chunks Successfully!!!")

        return jsonify({
            "message": f"Stored {len(chunks)} chunks from {file.filename}",
            "chunks_stored": len(chunks),
            "file": file.filename,
            "ids": ids
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
