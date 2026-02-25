import os
from google import genai
import dotenv

dotenv.load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)

print("Listing models...")
try:
    # The models are returned as a list of Model objects
    # We can try to print the entire object to see available attributes
    models = client.models.list()
    for m in models:
        # Check available attributes
        attrs = [a for a in dir(m) if not a.startswith('_')]
        print(f"Model Name: {m.name}")
        # print(f"Attributes: {attrs}")
except Exception as e:
    print(f"Error listing models: {e}")
    import traceback
    traceback.print_exc()
