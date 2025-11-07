import os, json, time, uuid, sqlite3
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import openai

app = FastAPI(title="EngageBoost Server")
DB = "engageboost.db"

def db():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

conn = db(); cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS licenses (id INTEGER PRIMARY KEY, key TEXT UNIQUE, status TEXT DEFAULT 'active', created_at INTEGER)")
cur.execute("CREATE TABLE IF NOT EXISTS redeem_codes (id INTEGER PRIMARY KEY, code TEXT UNIQUE, status TEXT DEFAULT 'unused', license_key TEXT, created_at INTEGER, redeemed_at INTEGER)")
conn.commit()
if not cur.execute("SELECT id FROM redeem_codes WHERE code='TESTCODE123'").fetchone():
    cur.execute("INSERT INTO redeem_codes (code,status,created_at) VALUES ('TESTCODE123','unused',?)",(int(time.time()),))
    conn.commit()
cur.execute(
    "INSERT OR IGNORE INTO licenses (key, status, created_at) VALUES (?, 'active', ?)",
    ("ENG-4419EF48", int(time.time()))
)
conn.commit()

@app.get("/redeem.html", response_class=HTMLResponse)
async def redeem_page():
    return HTMLResponse('''<!doctype html><html><head><meta charset="utf-8"><title>EngageBoost — Redeem</title></head>
<body style="font-family:system-ui;margin:40px">
<h2>Enter your AppSumo Code</h2>
<input id="code" placeholder="e.g. TESTCODE123" style="padding:8px;width:300px">
<button onclick="go()" style="padding:8px 12px">Redeem</button>
<div id="out" style="margin-top:12px"></div>
<script>
async function go(){
  const r=await fetch('/redeem',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.getElementById('code').value.trim()})});
  const d=await r.json();
  document.getElementById('out').innerText = r.ok ? ('License: '+d.license) : (d.detail||'Error');
}
</script></body></html>''')

@app.post("/redeem")
async def redeem(payload: dict):
    code = (payload.get("code") or "").strip()
    c = db().cursor()
    row = c.execute("SELECT * FROM redeem_codes WHERE code=?", (code,)).fetchone()
    if not row: raise HTTPException(400, "Invalid code")
    if row["status"] == "used": raise HTTPException(400, "Code already redeemed")
    key = "ENG-" + uuid.uuid4().hex[:8].upper()
    c.execute("INSERT INTO licenses (key, created_at) VALUES (?, ?)", (key, int(time.time())))
    c.execute("UPDATE redeem_codes SET status='used', license_key=?, redeemed_at=? WHERE id=?", (key, int(time.time()), row["id"]))
    db().commit()
    return {"license": key}

@app.post("/generate")
async def generate(req: Request):
    client_key = req.headers.get("x-client-key")
    if not client_key: raise HTTPException(401, "Missing license key")
    c = db().cursor()
    if not c.execute("SELECT id FROM licenses WHERE key=? AND status='active'", (client_key,)).fetchone():
        raise HTTPException(401, "Invalid or inactive license")

    body = await req.json()
    text = (body.get("text") or "").strip()
    tone = (body.get("tone") or "Professional")
    if not text: raise HTTPException(400, "Missing text")

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(500, "Server missing OPENAI_API_KEY")
    openai.api_key = os.getenv("OPENAI_API_KEY")

    prompt = f"You are EngageBoost. Given this post:\n'''{text}'''\nTone: {tone}. Return a JSON array of 3 short, human comments."
    try:
        resp = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL","gpt-3.5-turbo"),
            messages=[{"role":"user","content":prompt}],
            temperature=0.7, max_tokens=200
        )
        content = resp.choices[0].message.content
        try:
            data = json.loads(content)
            if isinstance(data, list): return {"comments": data}
        except Exception:
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            return {"comments": lines[:3]}
    except Exception as e:
        raise HTTPException(500, str(e))
