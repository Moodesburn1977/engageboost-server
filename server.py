import os
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import openai

# Read your OpenAI API key from environment (set this in Render)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    # We won't crash the app, but we'll fail requests later with a clear message
    print("WARNING: OPENAI_API_KEY is not set. /generate will return 500.")
else:
    openai.api_key = OPENAI_API_KEY

app = FastAPI()

# Allow calls from your extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # you can restrict this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    text: str
    tone: str = "Professional"


class GenerateResponse(BaseModel):
    comments: List[str]


@app.get("/")
async def root():
    return {"status": "ok", "message": "EngageBoost server running"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    """
    Generate 3 short comment-style replies based on the input text and tone.
    NO license or x-client-key checks here.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: missing OPENAI_API_KEY."
        )

    base_prompt = (
        "You are an assistant that writes short, natural, human-sounding comments. "
        "Respond as if you are adding a reply or comment to the original text. "
        "Tone: {tone}.\n\n"
        "Original text:\n{body}\n\n"
        "Write 3 different short comments, numbered 1–3."
    )

    prompt = base_prompt.format(tone=req.tone, body=req.text)

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You write concise, friendly comments."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
    except Exception as e:
        # Bubble this back as a clean error message
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")

    content = completion.choices[0].message["content"].strip()

    # Split into lines and clean up
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    comments: List[str] = []

    for line in lines:
        # Remove leading numbers like "1)", "1.", etc.
        if line[0].isdigit():
            # Find first space after number and punctuation
            idx = 0
            while idx < len(line) and (line[idx].isdigit() or line[idx] in ".):-"):
                idx += 1
            line = line[idx:].strip()
        if line:
            comments.append(line)

    if not comments:
        comments = [content]

    # Return at most 3 comments
    return GenerateResponse(comments=comments[:3])


# For local testing (not used on Render typically)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
