from flask import Flask, request, jsonify
import json
from firebase_admin import firestore
import re

def ask(client, request, collection, db):
    try:
        data = request.get_json()

        # Extract incoming data
        user_query = data.get("user_query")
        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})
        grounded = data.get("grounded")

        

        # Separate data
        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])
        conversation_history = user_subject_json.get("conversation_history", [])

        # print(f"User ID: {user_id}")
        # print(f"Subject ID: {subject_id}")
        print(f"Resources (filters): {resources}")
        print("Grounded : ", grounded)
        grounded_text = ""
        if grounded == False :
            grounded_text = "if the retrived study material is empty then generate based on your current level of knowledge"


        # ✅ Fetch RAG context from Chroma based on resource metadata
        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[user_query],
                    n_results=5,
                    where={"resources": {"$in": resources}}  # metadata filter
                )

                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
                print(rag_context)
                print("RAG Context Retrieved ✅")
            except Exception as e:
                print(f"RAG fetch failed: {e}")
                rag_context = ""
        else:
            rag_context = ""

        # ✅ Combine everything into the final prompt
        context = f"""
        Subject: {subject_name}

        Course Title: {syllabus.get('course_title', '')}

        Units:
        {json.dumps(syllabus.get('units', []), indent=2)}

        Resources (metadata filters): {', '.join(resources)}

        Previous Conversation:
        {json.dumps(conversation_history[-10:], indent=2)}

        Retrieved Study Material from ChromaDB:
        {rag_context}

        {grounded_text}
        """

        prompt = f"""
        You are an intelligent teaching assistant.
        Use the syllabus, resources, and retrieved content below to answer precisely.
        don't add markdown styles in the generated content

        Context:
        {context}

        Question: {user_query}
        """

        # ✅ Send to Gemini
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        ai_reply = response.text.strip()

        db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
            .update({"conversation_history": firestore.ArrayUnion([
                {"role": "user", "message": user_query},
                {"role": "system", "message": ai_reply}
            ])})

        # Return the combined result
        return jsonify({
            "reply": ai_reply,
            "user_id": user_id,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "rag_context": rag_context,
            "syllabus": syllabus,
            "conversation_history": conversation_history
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_question_bank(client, request, collection, db):
    try:
        data = request.get_json()

        # Extract incoming data
        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})

        # Separate data
        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])

        print(f"User ID: {user_id}")
        print(f"Subject ID: {subject_id}")
        print(f"Resources (filters): {resources}")

        # ✅ Fetch RAG context from Chroma based on resource metadata
        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[json.dumps(syllabus, indent=2)],
                    n_results=5,
                    where={"resource": {"$in": resources}}  # metadata filter
                )

                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
                print("RAG Context Retrieved ✅")
            except Exception as e:
                print(f"RAG fetch failed: {e}")
                rag_context = ""
        else:
            rag_context = ""

        prompt = f"""
            You are an intelligent university-level teaching assistant and question paper generator.

            You are given:
            - Subject name: {subject_name}
            - Syllabus: {json.dumps(syllabus, indent=2)}
            - Retrieved Study Material (from resources): {rag_context} \n\n
            - if the retrived study material is empty then generate based on your current level of knowledge

            Your task:
            Generate a **comprehensive question bank** based on the syllabus and retrieved material.
            Follow these rules carefully:

            1. Cover every **unit** and **topic** in the syllabus.
            2. Include **conceptual**, **analytical**, and **application-based** questions.
            3. Classify questions into four categories based on marks and depth:
            - **2 Marks:** Short, direct answer questions.
            - **16 Marks:** In-depth, problem-solving or case study questions.
            4. Do NOT repeat or rephrase the same idea in multiple questions.
            5. Ensure questions are relevant, balanced, and follow academic standards.
            6. generate 10 **2 marks** and 10 **16 marks** per unit.

            Now generate the full question bank strictly in the given format.

            Return your output strictly in this **JSON format**:
            {{
            "course_title": "",
            "units": [
                {{
                    "unit_number": "",
                    "unit_title": "",
                    "2_marks": ["", "", ""],
                    "16_marks": ["", "", ""]
                }}
            ]
            }}
        """

        # ✅ Send to Gemini
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        raw = response.text.strip()

         # Handle possible double-encoded JSON
        try:
            # 1️⃣ Remove Markdown code block markers like ```json ... ```
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
            cleaned = re.sub(r"```$", "", cleaned).strip()

            # 2️⃣ Extract JSON body between braces
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise ValueError("No JSON structure found in Gemini output")

            json_str = match.group(0)

            # 3️⃣ Try loading the JSON
            data = json.loads(json_str)

            # 4️⃣ Handle potential double-encoded JSON strings
            if isinstance(data, str):
                data = json.loads(data)

        except Exception as e:
            return jsonify({
                "error": f"Failed to parse JSON from Gemini: {str(e)}",
                "raw_output": raw
            }), 500

        db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
            .set({"question_bank": data}, merge=True)

        # Return the combined result
        return jsonify({
            "reply": data,
            "user_id": user_id,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "rag_context": rag_context,
            "syllabus": syllabus
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_documentation(client, request, collection, db):
    try:
        data = request.get_json()

        # Extract incoming data
        user_id = data.get("user_id")
        subject_id = data.get("subject_id")
        user_subject_json = data.get("user_subject_json", {})

        # Separate data
        subject_name = user_subject_json.get("subject_name", "")
        syllabus = user_subject_json.get("syllabus", {})
        resources = user_subject_json.get("resources", [])

        print(f"User ID: {user_id}")
        print(f"Subject ID: {subject_id}")
        print(f"Resources (filters): {resources}")

        # ✅ Fetch RAG context from Chroma based on resource metadata
        rag_context = ""
        if resources:
            try:
                results = collection.query(
                    query_texts=[json.dumps(syllabus, indent=2)],
                    n_results=5,
                    where={"resource": {"$in": resources}}  # metadata filter
                )

                rag_docs = results.get("documents", [[]])[0]
                rag_context = "\n\n".join(rag_docs)
                print("RAG Context Retrieved ✅")
            except Exception as e:
                print(f"RAG fetch failed: {e}")
                rag_context = ""
        else:
            rag_context = ""

        prompt = f"""
            You are an expert academic content creator and university professor.

            Your goal is to generate **comprehensive, structured subject documentation** 

            You are given:
            - Subject name: {subject_name}
            - Syllabus: {json.dumps(syllabus, indent=2)}
            - Retrieved Study Material (from resources): {rag_context} \n\n
            - if the retrived study material is empty then generate based on your current level of knowledge

            ### Task Instructions

            Create a **complete subject documentation** covering all units and topics in the syllabus.  
            Ensure your content is:
            1. **Well-organized** — divided into clear Units, Topics, and Subtopics.
            2. **Educational** — include definitions, explanations, real-world examples, and use-cases.
            5. **Student-friendly** — summarize key takeaways and provide short Q&A at the end of each topic.
            6. **Comprehensive** — expand each unit into detailed conceptual and analytical content.

            Now generate the full question bank strictly in the given format.

            Return your output strictly in this **JSON format**:
            {{
                "course_title": "string",
                "overview": "string",
                "units": [
                    {{
                    "unit_number": "I",
                    "unit_title": "string",
                    "topics": [
                        {{
                        "topic_title": "string",
                        "explanation": "detailed text explanation",
                        "examples": ["example 1", "example 2"],
                        "real_world_applications": ["application 1", "application 2"],
                        "summary": "short topic summary"
                        }}
                    ],
                    "unit_summary": "brief overview of the unit"
                    }}
                ],
                "final_summary": "concise summary of the entire subject and its importance"
            }}
        """

        # ✅ Send to Gemini
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        raw = response.text.strip()

         # Handle possible double-encoded JSON
        try:
            # 1️⃣ Remove Markdown code block markers like ```json ... ```
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
            cleaned = re.sub(r"```$", "", cleaned).strip()

            # 2️⃣ Extract JSON body between braces
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise ValueError("No JSON structure found in Gemini output")

            json_str = match.group(0)

            # 3️⃣ Try loading the JSON
            data = json.loads(json_str)

            # 4️⃣ Handle potential double-encoded JSON strings
            if isinstance(data, str):
                data = json.loads(data)

        except Exception as e:
            return jsonify({
                "error": f"Failed to parse JSON from Gemini: {str(e)}",
                "raw_output": raw
            }), 500

        db.collection("users").document(user_id) \
            .collection("subjects").document(subject_id) \
            .set({"documentation": data}, merge=True)

        # Return the combined result
        return jsonify({
            "reply": data,
            "user_id": user_id,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "rag_context": rag_context,
            "syllabus": syllabus
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

