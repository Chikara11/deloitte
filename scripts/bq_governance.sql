-- AuditBridge — BigQuery governance (run in the BigQuery console, project deloitteinnov26par-598)

-- 1. One-time: add hash-chain columns to the existing audit table (no-op if present)
ALTER TABLE `war_room.audit_logs`
  ADD COLUMN IF NOT EXISTS prev_hash STRING,
  ADD COLUMN IF NOT EXISTS hash STRING;

-- 2. Are logs arriving? (last 30 min, per tenant and event type)
SELECT deal_id AS tenant_id, event_type, severity, COUNT(*) AS n, MAX(timestamp) AS last_seen
FROM `war_room.audit_logs`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY 1, 2, 3
ORDER BY last_seen DESC;

-- 3. Security events only (for the demo slide)
SELECT timestamp, deal_id AS tenant_id, agent_name, event_type, details_json
FROM `war_room.audit_logs`
WHERE severity = 'CRITICAL'
ORDER BY timestamp DESC
LIMIT 20;

-- 4. Hash chain continuity check in SQL: each event's prev_hash must equal the previous event's hash.
--    Rows returned = broken links (expected: 0). Rows written before the hash columns existed are skipped,
--    and a chain restart (prev_hash = 64 zeros, after a Cloud Run restart) is not counted as a break.
--    The chain lives in one instance's memory: keep Cloud Run at --max-instances=1 for the demo.
SELECT tenant_id, event_id, timestamp, prev_hash, expected_prev_hash
FROM (
  SELECT deal_id AS tenant_id, event_id, timestamp, prev_hash,
         LAG(hash) OVER (PARTITION BY deal_id ORDER BY timestamp, event_id) AS expected_prev_hash
  FROM `war_room.audit_logs`
  WHERE hash IS NOT NULL
)
WHERE expected_prev_hash IS NOT NULL
  AND prev_hash != expected_prev_hash
  AND prev_hash != REPEAT('0', 64);
