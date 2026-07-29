import time
from google.genai import errors

# Define active production models (Primary + Fallback)
TEXT_MODEL = "gemini-1.5-flash"
FALLBACK_MODEL = "gemini-2.0-flash"

def generate_content_with_retry(gemini_client, prompt, max_retries=3):
    models_to_try = [TEXT_MODEL, FALLBACK_MODEL]
    
    for model_name in models_to_try:
        print(f"--- Attempting generation with model: {model_name} ---")
        for attempt in range(1, max_retries + 1):
            try:
                print(f"Generating AI Content (Attempt {attempt}/{max_retries})...")
                response = gemini_client.models.generate_content(
                    model=model_name, 
                    contents=prompt
                )
                if response.text:
                    return response.text.strip()
                
            except errors.ClientError as e:
                # 404 Not Found or 400 Bad Request: stop retrying this bad model name
                print(f"ClientError with model '{model_name}': {e.message if hasattr(e, 'message') else e}")
                print("Switching model...")
                break  # Exit retry loop and switch to FALLBACK_MODEL
                
            except errors.ServerError as e:
                # 503 Server Busy or 500 Error: pause and retry
                print(f"Attempt {attempt} failed (Server Busy): {e.message if hasattr(e, 'message') else e}")
                if attempt < max_retries:
                    wait_time = attempt * 10
                    print(f"Waiting {wait_time}s before retrying...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                print(f"Unexpected error with model '{model_name}': {e}")
                break

    raise RuntimeError("Failed content generation after testing all available models.")
