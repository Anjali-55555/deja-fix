"""Retain sample past incidents into Hindsight. Safe to re-run (same content is deduplicated by document id)."""
import datetime as dt, hashlib
from app import hs, BANK
INCIDENTS = [
 ("INC-0012","payment-api","Payment API HTTP 500 errors","database connection pool reached its max of 50 connections under peak traffic","Increased pool from 50 to 100 and restarted the service","resolved",14,"Alert on pool utilisation above 80%. Restarting alone did not help the first time."),
 ("INC-0019","auth-service","Auth service login timeouts","Redis session cache evicted keys after a memory limit change","Raised Redis maxmemory and warmed the cache","resolved",22,"Never change maxmemory on Friday deploys."),
 ("INC-0027","order-service","Order service p99 latency spike","slow query after migration missing an index on orders.customer_id","Added the index concurrently","resolved",31,"Run EXPLAIN on new migrations."),
 ("INC-0031","payment-api","Payment API timeouts to database","connection leak in retry logic; restarting only partially helped","Restarted service, then patched the leak in the retry handler","partial",47,"Restart is a stopgap for pool problems, not a fix."),
 ("INC-0040","notification-service","Notification queue backlog","consumer crash loop after bad config deploy","Rolled back the deploy","resolved",9,"Roll back first, debug after."),
]
for i, s, t, cause, fix, out, mins, lesson in INCIDENTS:
    content = f"Incident {i} in {s}: {t}. Root cause: {cause}. Action taken: {fix}. Outcome: {out}, {mins} minutes. Lessons: {lesson}"
    hs.retain(bank_id=BANK, content=content, context="production incident",
              timestamp=dt.datetime.utcnow().isoformat() + "Z",
              document_id=hashlib.md5(i.encode()).hexdigest())
    print("retained", i)
