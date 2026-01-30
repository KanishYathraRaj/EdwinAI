from utils import extract_text_from_pdf, chunk_text
from firebase_admin import firestore
from flask import jsonify, request as flask_request
import os

def upsert_resources(request, chroma_collection, embedder, db):
    try:

        user_id = request.form.get("user_id")
        subject_id = request.form.get("subject_id")
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

        db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
            .set({"resources": firestore.ArrayUnion([
                file.filename
            ])}, merge=True)
        
        print("Stored the Chunks Successfully!!!")

        return jsonify({
            "message": f"Stored {len(chunks)} chunks from {file.filename}",
            "chunks_stored": len(chunks),
            "file": file.filename,
            "ids": ids
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
