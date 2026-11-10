INCIDENT_ID: PG-POOL-53300
CATEGORY: PostgreSQL
SEVERITY: CRITICAL
ERROR_CODE: SQLSTATE 53300 / FATAL: sorry, too many clients already / remaining connection slots are reserved
SYMPTOM: Services fail with `psycopg2.OperationalError: FATAL: remaining connection slots are reserved for non-replication superuser connections`.
ROOT CAUSE: Total client connections hit `max_connections` (default 100) due to missing connection pooling or leaked `idle in transaction` sessions.
DIAGNOSTICS:
1. Group connections by state and user: `SELECT usename, state, count(*) FROM pg_stat_activity GROUP BY usename, state;`
2. Find connections stuck in transaction > 5m: `SELECT pid, usename, state, query FROM pg_stat_activity WHERE state = 'idle in transaction' AND (now() - state_change) > interval '5 minutes';`
REMEDIATION:
1. Terminate leaked idle connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND (now() - state_change) > interval '5 minutes' AND pid <> pg_backend_pid();`
2. Configure SQLAlchemy connection pool limits: `create_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True)`
3. Deploy PgBouncer in `pool_mode = transaction`.
===
INCIDENT_ID: PG-DEADLOCK-40P01
CATEGORY: PostgreSQL
SEVERITY: HIGH
ERROR_CODE: SQLSTATE 40P01 / ERROR: deadlock detected / Process waits for ShareLock on transaction
SYMPTOM: Concurrent database writes fail intermittently with `psycopg2.extensions.TransactionRollbackError: deadlock detected DETAIL: Process 14902 waits for ShareLock on transaction 88921; blocked by process 14955`.
ROOT CAUSE: Two or more concurrent transactions lock rows in opposite orders (e.g., Transaction A locks Row 1 then requests Row 2, while Transaction B locks Row 2 then requests Row 1). After `deadlock_timeout` (default 1s), PostgreSQL aborts one transaction to break the cycle.
DIAGNOSTICS:
1. Inspect active lock wait trees in real time:
   `SELECT blocked_locks.pid AS blocked_pid, blocking_locks.pid AS blocking_pid, blocked_activity.query AS blocked_query, blocking_activity.query AS blocking_query FROM pg_catalog.pg_locks blocked_locks JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype AND blocking_locks.pid != blocked_locks.pid JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid WHERE NOT blocked_locks.granted;`
2. Enable deadlock logging in `postgresql.conf`: `log_lock_waits = on`
REMEDIATION:
1. Enforce deterministic lock ordering in application code: Always sort primary keys in ascending order (`ORDER BY id ASC`) before executing bulk `UPDATE` or `SELECT ... FOR UPDATE` statements.
2. Keep transactions short and never perform external HTTP calls inside an open `BEGIN ... COMMIT` block.
===
INCIDENT_ID: PG-WAL-DISK-53100
CATEGORY: PostgreSQL
SEVERITY: CRITICAL
ERROR_CODE: SQLSTATE 53100 / PANIC: could not write to file "pg_wal/xlogtemp": No space left on device
SYMPTOM: PostgreSQL database crashes and refuses to restart. Server logs show `PANIC: could not write to file "pg_wal/xlogtemp.1029": No space left on device`.
ROOT CAUSE: The Write-Ahead Log (`pg_wal`) directory filled 100% of disk capacity. This usually happens when an inactive Replication Slot (`pg_replication_slots`) prevents PostgreSQL from recycling old WAL segments because a replica or Debezium CDC connector disconnected.
DIAGNOSTICS:
1. Check disk usage of the `pg_wal` directory on Linux: `du -sh /var/lib/postgresql/data/pg_wal`
2. Identify inactive replication slots retaining massive WAL bytes:
   `SELECT slot_name, plugin, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal FROM pg_replication_slots;`
REMEDIATION:
1. Drop the abandoned inactive replication slot immediately so PostgreSQL purges old WAL files on the next checkpoint:
   `SELECT pg_drop_replication_slot('abandoned_slot_name');`
2. Run a manual checkpoint to reclaim disk space: `CHECKPOINT;`
3. Set `max_slot_wal_keep_size = 10GB` in `postgresql.conf` to prevent any dead replica from crashing the primary disk in the future.
===
INCIDENT_ID: PG-XID-WRAPAROUND-22000
CATEGORY: PostgreSQL
SEVERITY: CRITICAL
ERROR_CODE: ERROR: database is not accepting commands to avoid wraparound data loss in database
SYMPTOM: All write queries fail with `ERROR: database is not accepting commands to avoid wraparound data loss in database "prod_db" HINT: Stop the postmaster and vacuum that database in single-user mode`.
ROOT CAUSE: PostgreSQL uses 32-bit Transaction IDs (XIDs). If tables go ~2 billion transactions without `autovacuum` freezing old row versions (`relfrozenxid`), PostgreSQL halts all writes to prevent transaction ID wraparound (where historical data would appear to be in the future and become invisible).
DIAGNOSTICS:
1. Check transaction ID age across all databases:
   `SELECT datname, age(datfrozenxid), current_setting('autovacuum_freeze_max_age') FROM pg_database ORDER BY 2 DESC;`
2. Find the exact tables blocking freeze progress:
   `SELECT c.oid::regclass as table_name, age(c.relfrozenxid) as xid_age FROM pg_class c WHERE c.relkind IN ('r', 'm') ORDER BY 2 DESC LIMIT 10;`
REMEDIATION:
1. Run an aggressive manual `VACUUM FREEZE` on the oldest tables:
   `VACUUM (FREEZE, VERBOSE, INDEX_CLEANUP OFF) schema.table_name;`
2. Increase autovacuum worker resources so background vacuuming keeps pace with high write throughput:
   `ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 2000; SELECT pg_reload_conf();`