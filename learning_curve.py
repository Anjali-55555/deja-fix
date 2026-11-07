"""Scripted learning-curve demo: same kind of incident, agent gets better each round.

Run the server first (uvicorn app:app --reload), seed with seed_incidents.py, then:
    python learning_curve.py
Record your screen while this runs, or copy the rounds into the UI by hand.
"""
import httpx

URL = "http://localhost:8000"

ROUNDS = [
    # (label, use_memory, incident)
    ("Round 1 - memory OFF (generic baseline)", False,
     {"service": "billing-api", "title": "Billing API 500 errors at month-end",
      "description": "Spike of 500s during invoice run",
      "logs": "HikariPool-1 - Connection is not available, request timed out after 30000ms"}),
    ("Round 2 - memory ON (recalls payment-api pool incidents)", True,
     {"service": "billing-api", "title": "Billing API 500 errors at month-end",
      "description": "Spike of 500s during invoice run",
      "logs": "HikariPool-1 - Connection is not available, request timed out after 30000ms"}),
]

def run(label, use_memory, inc):
    r = httpx.post(f"{URL}/api/investigate", json={**inc, "use_memory": use_memory}, timeout=120)
    d = r.json()
    print("=" * 70, f"\n{label}\nmemories recalled: {len(d['memories'])}\n")
    print(d["plan"][:900], "\n")

def resolve_and_teach():
    body = {"incident_id": "INC-0200", "title": "Billing API 500 errors at month-end",
            "service": "billing-api", "outcome": "resolved",
            "root_cause": "Pool exhaustion during invoice run plus unclosed connections in batch job",
            "action_taken": "Raised pool 50->120 and fixed connection close in batch job",
            "minutes": 14, "lessons": "Month-end batch jobs need their own pool.",
            "suggestion_worked": True}
    print("=" * 70, "\nResolving INC-0200 and saving it to memory...")
    print(httpx.post(f"{URL}/api/resolve", json=body, timeout=120).json().get("saved"))

if __name__ == "__main__":
    run(*ROUNDS[0])
    run(*ROUNDS[1])
    resolve_and_teach()
    run("Round 3 - NEW similar incident (now cites INC-0200 too)", True,
        {"service": "invoicing-worker", "title": "Invoicing worker timeouts",
         "description": "Nightly invoicing job failing intermittently",
         "logs": "Timeout waiting for connection from pool; leak detection threshold exceeded"})
