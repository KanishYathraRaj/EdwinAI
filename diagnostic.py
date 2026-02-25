print("Starting diagnostic...")
import os
print("Imported os")
import flask
print("Imported flask")
from flask_cors import CORS
print("Imported flask_cors")
import fitz
print("Imported fitz")
import chromadb
print("Imported chromadb")
from sentence_transformers import SentenceTransformer
print("Imported sentence_transformers")
import firebase
print("Imported firebase")
import llm_provider
print("Imported llm_provider")
import llm
print("Imported llm")
print("All imports successful")

llm_client = llm_provider.get_llm_client()
print("Initialized llm_client")
embedder = SentenceTransformer("all-MiniLM-L6-v2")
print("Initialized embedder")
chroma_client = chromadb.PersistentClient(path="./chromaDB")
print("Initialized chroma_client")
print("Diagnostic finished successfully")
