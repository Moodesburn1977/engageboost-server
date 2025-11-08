import os
import json
import time
import uuid
import sqlite3

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import openai

app = FastAPI(title="EngageBoost Server")
DB = "engageboost.db"

# ---------- Database helper ----------
def db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- Initialize tables ----------
conn = db()
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    created_at INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS redeem_codes (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,
    status TEXT DEFAULT 'unused',
    license_key TEXT,
    created_at INTEGER,
    redeemed_at INTEGER
)
""")

conn.commit()

# ---------- Seed default redeem code ----------
if not cur.execute("SELECT id FROM redeem_codes WHERE code='TESTCODE123'").fetchone():
    cur.execute(
        "INSERT INTO redeem_codes (code, status, created_at) VALUES ('TESTCODE123','unused',?)",
        (int(time.time()),)
    )
    conn.commit()

# ---------- Seed default licenses ----------
# These are always treated as valid & active if used by the extension.
for key in ("ENG-4419EF48", "ENG-8EF49C16"):
    cur.execute(
        "INSERT OR IGNORE INTO licenses (key, status, created_at) VALUES (?, 'active', ?)",
        (key, int(time.time()))
    )

conn.commit()

# ---------- Health / root ----------
@app.get("/")
async def root():
    return {"status": "ok", "message": "EngageBoost server running"}

# ---------- Redeem Page ----------
@app.get("/redeem.html", response_class=HTMLResponse)
async def redeem_page():
    return HTMLResponse(
        """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>EngageBoost — Redeem</title>
  </head>
  <body style="font-family: system-ui; margin: 40px">
    <h2>Enter your AppSumo Code</h2>
    <input id="code" placeholder="e.g. TESTCODE123" style="padding:8px;width:300px">
    <button onclick="go()" style="padding:8px 12px">Redeem</button>
    <div id="out" style="margin-top:12px"></div>
    <script>
      async function go() {
        const code = document.getElementById('code').value.trim();
        const res = await fetch('/redeem', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ code })
        });
        const data = await res.json();
        document.getElementById('out').innerText =
          res.ok ? ('License: ' + data.license) : (data.detail || 'Error');
      }
    </script>
  </body>
</html>"""
    )

# ---------- Redeem API ----------
@app.post("/redeem")
async def redeem(payload: dict):
    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "Missing code")

    conn = db()
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM redeem_codes WHERE code=?",
        (code,)
    ).fetchone()

    if not row:
        raise HTTPException(400, "Invalid code")
    if row["status"] == "used":
        raise HTTPException(400, "Code already redeemed")

    # Generate a new license key for this code
    key = "ENG-" + uuid.uuid4().hex[:8].upper()
    now = int(time.time())

    c.execute(
        "INSERT INTO licenses (key, status, created_at) VALUES (?, 'active', ?)",
        (key, now)
    )
    c.execute(
        "UPDATE redeem_codes SET status='used', license_key=?, redeemed_at=? WHERE id=?",
        (key, now, row["id"])
    )
    conn.commit()

    return {"license": key}

# ---------- Generate API ----------
@app.post("/generate")
async def generate(req: Request):
    # 1. Check license
    client_key = req.headers.get("x-client-key")
    if not client_key:
        raise HTTPException(401, "Missing license key")

    conn = db()
    c = conn.cursor()
    license_row = c.execute(
        "SELECT id FROM licenses WHERE key=? AND status='active'",
        (client_key,)
    ).fetchone()

    if not license_row:
        raise HTTPException(401, "Invalid or inactive license")

    # 2. Read request body
    body = await req.json()
    text = (body.get("text") or "").strip()
    tone = (body.get("tone") or "Professional").strip()

    if not text:
        raise HTTPException(400, "Missing text")

    # 3. Check OpenAI key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "Server missing OPENAI_API_KEY")

    openai.api_key = api_key

    # 4. Build prompt
    prompt = (
        "You are EngageBoost. Given this social media post:\\n"
        f"'''{text}'''\\n"
        f"Write 3 short, natural, human-sounding comments in a {tone} tone.\\n"
        "Return ONLY a JSON array of 3 strings."
    )

    # 5. Call OpenAI (using openai==0.28.0 style)
    try:
        resp = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()

        # Try to parse JSON array
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {"comments": data}
        except Exception:
            # Fallback: split into lines
            lines = [line.strip(" -•") for line in content.splitlines() if line.strip()]
            return {"comments": lines[:3]}

    except Exception as e:
        raise HTTPException(500, f"OpenAI error: {str(e)}")
