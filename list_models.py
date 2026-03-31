from app.config import settings
import google.generativeai as genai

genai.configure(api_key=settings.GEMINI_API_KEY)

for m in genai.list_models():
    if 'embedContent' in m.supported_generation_methods:
        print(m.name)
