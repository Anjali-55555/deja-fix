import os, datetime as dt
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from hindsight_client import Hindsight
import httpx

load_dotenv()
BANK = os.getenv("HINDSIGHT_BANK_ID", "dejafix-incidents")
hs = Hindsight(base_url=os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888"),
               api_key=os.getenv("HINDSIGHT_API_KEY") or None)
app = FastAPI(title="Deja Fix")
last_op = {"op": None, "ok": None, "at": None}

def mark(op, ok):
    last_op.update(op=op, ok=ok, at=dt.datetime.utcnow().isoformat() + "Z")

class Incident(BaseModel):
    title: str
    service: str = ""
    description: str = ""
    logs: str = ""
    use_memory: bool = True

class Resolution(BaseModel):
    incident_id: str
    title: str
    service: str
    outcome: str  # resolved | partial | unresolved
    root_cause: str
    action_taken: str
    minutes: int | None = None
    lessons: str = ""
    suggestion_worked: bool | None = None

def recall(query: str, limit: int = 5):
    try:
        res = hs.recall(bank_id=BANK, query=query)
        mark("recall", True)
        return [{"text": r.text, "context": getattr(r, "context", None)}
                for r in res.results[:limit]], None
    except Exception as e:
        print("Hindsight recall error:", e)
        mark("recall", False)
        return [], "Hindsight temporarily unavailable"

def llm(prompt: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return "LLM not configured: set GROQ_API_KEY."
    for model in (os.getenv("LLM_MODEL"), os.getenv("LLM_FALLBACK_MODEL")):
        try:  # retry on fallback model if the first fails (function-calling/format errors)
            r = httpx.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"}, timeout=60,
                json={"model": model, "messages": [
                    {"role": "system", "content": "You are an SRE Incident-response agent. Ground advice ONLY in the provided memories when citing history. If no memories are given, say no relevant memory was found and give generic steps. Never invent past incidents."},
                    {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception:
            continue
    return "LLM unavailable, try again."

@app.post("/api/investigate")
def investigate(inc: Incident):
    query = f"{inc.service} {inc.title}. {inc.description} {inc.logs[:500]}"
    memories, err = recall(query) if inc.use_memory else ([], None)
    mem_txt = "\n".join(f"[M{i+1}] {m['text']}" for i, m in enumerate(memories)) or "NONE"
    plan = llm(f"New incident:\nService: {inc.service}\nTitle: {inc.title}\n{inc.description}\nLogs:\n{inc.logs[:1500]}\n\n"
               f"Retrieved past-incident memories:\n{mem_txt}\n\n"
               "Give: likely causes, a numbered action plan, and for each step cite the memory [M#] "
               "that supports it (or 'no memory'). Mention any past fix that failed.")
    return {"memories": memories, "memory_error": err, "plan": plan, "memory_used": inc.use_memory}

@app.post("/api/resolve")
def resolve(r: Resolution):
    worked = {True: "The agent's suggestion worked.", False: "The agent's suggestion did NOT work.", None: ""}[r.suggestion_worked]
    content = (f"Incident {r.incident_id} in {r.service}: {r.title}. Root cause: {r.root_cause}. "
               f"Action taken: {r.action_taken}. Outcome: {r.outcome}"
               f"{f', resolved in {r.minutes} minutes' if r.minutes else ''}. "
               f"Lessons: {r.lessons} {worked}").strip()
    try:
        hs.retain(bank_id=BANK, content=content, context="production incident",
                  timestamp=dt.datetime.utcnow().isoformat() + "Z")
        mark("retain", True)
        return {"saved": True, "memory": content}
    except Exception:
        mark("retain", False)
        return {"saved": False, "error": "Hindsight temporarily unavailable"}

@app.get("/api/memories")
def memories(q: str = "recurring incidents"):
    m, err = recall(q, 10)
    return {"memories": m, "error": err}

@app.get("/api/reflect")
def reflect(q: str = "What recurring failure patterns do we have and which fixes worked or failed?"):
    try:
        a = hs.reflect(bank_id=BANK, query=q); mark("reflect", True)
        return {"text": a.text}
    except Exception:
        mark("reflect", False)
        return {"text": None, "error": "Hindsight temporarily unavailable"}

@app.get("/api/health/hindsight")
def health():
    configured = bool(os.getenv("HINDSIGHT_BASE_URL"))
    try:
        hs.recall(bank_id=BANK, query="health check"); connected = True
    except Exception:
        connected = False
    return {"configured": configured, "connected": connected, "bankId": BANK, "lastOperation": last_op}

@app.get("/")
def index():
    return FileResponse("static/index.html")
