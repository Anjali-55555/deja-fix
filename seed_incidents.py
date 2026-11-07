"""Load ~24 realistic past incidents into Hindsight. Safe to re-run (deduplicated by document id).

Usage (from the project root, with .env filled in):
    python seed_incidents.py
Retains can take a few seconds each, so give it a minute or two.
"""
import datetime as dt, hashlib
from app import hs, BANK

# (id, service, title, log_line, root_cause, failed_attempts, fix, outcome, minutes, lesson, days_ago)
INCIDENTS = [
 ("INC-0101","payment-api","Payment API HTTP 500 spike","HikariPool-1 - Connection is not available, request timed out after 30000ms","DB connection pool capped at 50 under checkout peak","Restarted pods; errors returned within 10 min","Raised pool 50->100 and added pool-utilisation alert at 80%","resolved",38,"Restart is a stopgap for pool exhaustion.",150),
 ("INC-0102","order-service","Order creation timeouts","psycopg2.OperationalError: FATAL: remaining connection slots are reserved","Pool exhaustion after a traffic campaign","Scaled replicas up, which made it worse (more connections)","Lowered per-pod pool size and added PgBouncer","resolved",55,"Scaling replicas multiplies DB connections.",141),
 ("INC-0103","reporting-api","Report export hangs","QueuePool limit of size 10 overflow 10 reached, connection timed out","Long-running exports holding connections","Increased gunicorn timeout, no effect","Moved exports to async worker with its own pool","resolved",70,"Isolate heavy jobs from the request pool.",133),
 ("INC-0104","auth-service","Login timeouts","redis.exceptions.ResponseError: OOM command not allowed when used memory > 'maxmemory'","Redis session cache hit maxmemory and evicted keys","Flushed cache, which logged out every user","Raised maxmemory, set allkeys-lru policy, warmed cache","resolved",26,"Never flush a session cache in prod.",128),
 ("INC-0105","auth-service","Intermittent 401s after deploy","JWT signature verification failed: key id not found","Rotated signing key not propagated to all pods","Rolled back image only, keys still mismatched","Redeployed secret and restarted all pods together","resolved",34,"Rotate keys with overlap; keep old key valid for 24h.",120),
 ("INC-0106","order-service","p99 latency spike after migration","Seq Scan on orders (cost=0.00..184523.12) filter: customer_id","Migration dropped index on orders.customer_id","Added more DB CPU, no change","Recreated index CONCURRENTLY","resolved",31,"Run EXPLAIN on every new migration.",113),
 ("INC-0107","inventory-service","Stock counts wrong","deadlock detected; process 4412 waits for ShareLock on transaction 99812","Two workers updating the same SKU rows in opposite order","Retried failed jobs, deadlocks continued","Enforced consistent row lock ordering by SKU id","resolved",90,"Lock in a deterministic order.",106),
 ("INC-0108","notification-service","Notification queue backlog","consumer exited with code 1: invalid config key 'smtp_hots'","Typo in config deploy caused consumer crash loop","Scaled consumers up, all crashed","Rolled back the config deploy","resolved",9,"Roll back first, debug after.",99),
 ("INC-0109","payment-api","Payment timeouts to DB","Timeout waiting for connection from pool; leak detection threshold exceeded","Connection leak in retry handler (never closed on exception)","Restarted service; helped for an hour","Restarted, then patched retry handler to close connections in finally","partial",47,"If a restart only helps briefly, look for a leak.",92),
 ("INC-0110","gateway","502 Bad Gateway from edge","upstream prematurely closed connection while reading response header","Upstream keepalive timeout shorter than gateway idle timeout","Increased gateway timeouts, no change","Aligned keepalive: upstream 75s, gateway 60s","resolved",44,"Gateway idle timeout must be lower than upstream keepalive.",85),
 ("INC-0111","search-service","Search returns stale results","indexer lag: 4.2M docs behind, last commit 3h ago","Indexer paused by disk watermark on ES node","Restarted indexer, still paused","Freed disk, cleared read-only block on index","resolved",62,"Alert on disk > 80% on data nodes.",78),
 ("INC-0112","gateway","Sudden TLS handshake failures","x509: certificate has expired or is not yet valid","Internal service certificate expired","Restarted gateway, no effect","Renewed certificate and added expiry alert at 30 days","resolved",21,"Monitor cert expiry; never rely on memory.",71),
 ("INC-0113","payment-api","Payment API 500s again","HikariPool-1 - Connection is not available","Pool exhaustion during sale event","Restarted pods first (known to fail from INC-0101)","Raised pool and enabled connection queueing","resolved",18,"Past incident cut resolution time from 38 to 18 minutes.",64),
 ("INC-0114","order-service","OOMKilled pods","Last State: Terminated Reason: OOMKilled Exit Code: 137","Memory leak in image-resize library after v2.3 upgrade","Raised memory limit 512Mi->1Gi; leak continued","Pinned library to v2.2 and filed upstream bug","resolved",75,"Raising limits hides leaks; check recent dependency bumps.",58),
 ("INC-0115","reporting-api","Nightly report job failed","ERROR: could not resize shared memory segment: No space left on device","Disk full from unrotated debug logs","Deleted tmp files, filled again next day","Enabled log rotation and cleaned /var/log","resolved",40,"Disk-full recurring means missing rotation.",52),
 ("INC-0116","auth-service","Login timeouts","redis.exceptions.ResponseError: OOM command not allowed","Redis evicted session keys after maxmemory change on Friday deploy","None (recognised from INC-0104)","Raised maxmemory, warmed cache","resolved",12,"Memory recall turned a 26 minute fix into 12.",47),
 ("INC-0117","inventory-service","Slow inventory sync","429 Too Many Requests from supplier-api (Retry-After: 60)","Third-party rate limit hit after batch size increase","Retried immediately, got blocked longer","Added exponential backoff and halved batch size","resolved",50,"Respect Retry-After; never retry immediately.",41),
 ("INC-0118","gateway","Partial outage in one region","dial tcp: lookup orders.internal: no such host","DNS resolver overloaded after cache TTL set to 0","Restarted gateway, DNS still failing","Restored DNS TTL to 30s and added local cache","resolved",58,"Never set TTL to 0 in a hot path.",36),
 ("INC-0119","notification-service","Duplicate emails sent","message redelivered: ack timeout exceeded (30s)","Consumer ack timeout shorter than slow template render","Reduced consumer count, still duplicates","Raised ack timeout to 120s and made sends idempotent","resolved",66,"Make consumers idempotent.",30),
 ("INC-0120","search-service","Search latency doubled","GC overhead limit: pause 4.8s old gen","JVM heap too small after index growth","Restarted node, relief for 20 min","Raised heap to 16g and added GC alert","partial",85,"Restart relief that fades means capacity, not a glitch.",24),
 ("INC-0121","payment-api","Checkout 500s on Friday","HikariPool-1 - Connection is not available","Pool exhaustion plus connection leak","Raised pool (fixed pool issue but leak remained)","Raised pool and deployed leak fix from INC-0109","resolved",29,"Check pool AND leak together.",17),
 ("INC-0122","order-service","Orders stuck in PENDING","Kafka consumer group rebalancing repeatedly","session.timeout.ms too low during GC pauses","Restarted consumers, rebalance storm repeated","Raised session.timeout.ms to 45s","resolved",52,"Frequent rebalances usually mean timeouts vs GC.",11),
 ("INC-0123","reporting-api","Dashboards blank","upstream connect error or disconnect/reset before headers","Bad config deploy changed upstream port","Cleared CDN cache, no effect","Rolled back config deploy","resolved",8,"Roll back config deploys first.",6),
 ("INC-0124","gateway","Elevated 502s at night","upstream prematurely closed connection","Keepalive mismatch reintroduced by new LB image","Restarted gateway pods","Reapplied keepalive alignment (see INC-0110)","resolved",15,"Keep keepalive alignment in IaC, not by hand.",2),
]

def main():
    now = dt.datetime.utcnow()
    for (i, svc, title, log, cause, failed, fix, out, mins, lesson, ago) in INCIDENTS:
        content = (f"Incident {i} in {svc}: {title}. Log signature: {log}. "
                   f"Root cause: {cause}. Fixes that did NOT work: {failed}. "
                   f"Action that fixed it: {fix}. Outcome: {out}, {mins} minutes. Lessons: {lesson}")
        ts = (now - dt.timedelta(days=ago)).isoformat() + "Z"
        hs.retain(bank_id=BANK, content=content, context="production incident",
                  timestamp=ts, document_id=hashlib.md5(i.encode()).hexdigest())
        print("retained", i, svc)

if __name__ == "__main__":
    main()
