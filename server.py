import os
import json
import time
import uuid
import sqlite3

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse
import openai

app = FastAPI(title="EngageBoost Server")
DB = "engageboost.db"


# ---------- DB helper ----------
def db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- Initialize tables ----------
conn = db()
cur = conn.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS licenses (
        id INTEGER PRIMARY KEY,
        key TEXT UNIQUE,
        status TEXT DEFAULT 'active',
        created_at INTEGER
    )
"""
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS redeem_codes (
        id INTEGER PRIMARY KEY,
        code TEXT UNIQUE,
        status TEXT DEFAULT 'unused',
        license_key TEXT,
        created_at INTEGER,
        redeemed_at INTEGER
    )
"""
)

conn.commit()

# ---------- Seed one test redeem code (for you) ----------
if not cur.execute(
    "SELECT id FROM redeem_codes WHERE code='TESTCODE123'"
).fetchone():
    cur.execute(
        "INSERT INTO redeem_codes (code, status, created_at) VALUES (?, 'unused', ?)",
        ("TESTCODE123", int(time.time())),
    )
    conn.commit()

conn.commit()


# ---------- Health check ----------
@app.get("/")
async def root():
    return {"status": "ok", "message": "EngageBoost server running"}


# ---------- Redeem Page (for buyers) ----------
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
    <h2>Enter your code to get your EngageBoost license</h2>
    <p>Paste the code you received from your purchase (e.g. AppSumo), then click Redeem.</p>
    <input id="code" placeholder="e.g. ASUMO-XXXX" style="padding:8px;width:320px">
    <button onclick="go()" style="padding:8px 14px;margin-left:4px;">Redeem</button>
    <div id="out" style="margin-top:14px;font-weight:500;"></div>
    <script>
      async function go() {
        const code = document.getElementById('code').value.trim();
        if (!code) {
          document.getElementById('out').innerText = 'Please enter a code.';
          return;
        }
        const res = await fetch('/redeem', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ code })
        });
        const data = await res.json();
        if (res.ok) {
          document.getElementById('out').innerText =
            'Your license key: ' + data.license +
            '\\nCopy this key and paste it into your EngageBoost Chrome extension settings.';
        } else {
          document.getElementById('out').innerText = data.detail || 'Error redeeming code.';
        }
      }
    </script>
  </body>
</html>
"""
    )


# ---------- Redeem API: code -> license ----------
@app.post("/redeem")
async def redeem(payload: dict):
    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "Missing code")

    conn = db()
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM redeem_codes WHERE code = ?", (code,)
    ).fetchone()

    if not row:
        raise HTTPException(400, "Invalid code")
    if row["status"] == "used":
        raise HTTPException(400, "Code already redeemed")

    # Create unique license key
    license_key = "ENG-" + uuid.uuid4().hex[:8].upper()
    now = int(time.time())

    c.execute(
        "INSERT INTO licenses (key, status, created_at) VALUES (?, 'active', ?)",
        (license_key, now),
    )
    c.execute(
        "UPDATE redeem_codes SET status='used', license_key=?, redeemed_at=? WHERE id=?",
        (license_key, now, row["id"]),
    )
    conn.commit()

    return {"license": license_key}


# ---------- Admin: generate redeem codes in bulk ----------
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()


@app.post("/admin/generate_redeem_codes")
async def admin_generate_redeem_codes(
    payload: dict, x_admin_key: str = Header(None)
):
    """
    Admin-only.
    Headers:
      x-admin-key: your ADMIN_KEY from environment
    Body JSON:
      {
        "prefix": "ASUMO",
        "count": 50
      }
    Returns:
      { "codes": ["ASUMO-XXXX...", ...] }
    """
    if not ADMIN_KEY:
        raise HTTPException(500, "ADMIN_KEY is not set on server")

    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")

    prefix = (payload.get("prefix") or "ASUMO").strip().upper()
    count = int(payload.get("count") or 1)

    if count < 1 or count > 1000:
        raise HTTPException(
            400, "count must be between 1 and 1000"
        )

    conn = db()
    c = conn.cursor()
    codes = []
    now = int(time.time())

    for _ in range(count):
        code = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
        try:
            c.execute(
                "INSERT INTO redeem_codes (code, status, created_at) VALUES (?, 'unused', ?)",
                (code, now),
            )
            codes.append(code)
        except Exception:
            # ignore duplicates if any collision
            pass

    conn.commit()
    return {"codes": codes}


# ---------- Generate comments (used by Chrome extension) ----------
@app.post("/generate")
async def generate(req: Request):
    # 1. Check license
    client_key = req.headers.get("x-client-key")
    if not client_key:
        raise HTTPException(401, "Missing license key")

    conn = db()
    c = conn.cursor()
    lic = c.execute(
        "SELECT id FROM licenses WHERE key=? AND status='active'",
        (client_key,),
    ).fetchone()

    if not lic:
        raise HTTPException(401, "Invalid or inactive license")

    # 2. Read body
    body = await req.json()
    text = (body.get("text") or "").strip()
    tone = (body.get("tone") or "Friendly").strip()

    if not text:
        raise HTTPException(400, "Missing text")

    # 3. OpenAI API key
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "Server missing OPENAI_API_KEY")

    openai.api_key = api_key

    # 4. Prompt
    prompt = (
        "You are EngageBoost, an assistant that writes natural, human-sounding social media comments.\n"
        f"Post:\n'''{text}'''\n"
        f"Tone: {tone}.\n"
        "Return ONLY a JSON array of 3 short, unique, human comments (strings). No explanations."
    )

    # 5. Call OpenAI (using openai==0.28 style)
    try:
        resp = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()

        # Try parse JSON array directly
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return {"comments": data}
        except Exception:
            # Fallback: split into lines if model didn't follow JSON perfectly
            lines = [
                line.strip(" -*•")
                for line in content.splitlines()
                if line.strip()
            ]
            return {"comments": lines[:3]}

    except Exception as e:
        raise HTTPException(500, f"OpenAI error: {str(e)}")
