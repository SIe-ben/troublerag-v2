INCIDENT_ID: REDIS-OOM-099
CATEGORY: Redis / Cache
SEVERITY: HIGH
ERROR_CODE: OOM command not allowed when used memory > 'maxmemory'
SYMPTOM: Write commands (`SET`, `LPUSH`) fail with `ResponseError: OOM command not allowed when used memory > 'maxmemory'`.
ROOT CAUSE: Redis RAM hit `maxmemory` and `maxmemory-policy` is set to `noeviction` or keys were inserted without a TTL (`EXPIRE`).
DIAGNOSTICS:
1. Check memory and policy: `redis-cli INFO memory | grep -E "used_memory_human|maxmemory_policy"`
2. Scan for huge keys safely: `redis-cli --bigkeys -i 0.01`
REMEDIATION:
1. Switch policy dynamically: `redis-cli CONFIG SET maxmemory-policy allkeys-lru`
2. Enable active memory defragmentation: `redis-cli CONFIG SET activedefrag yes`
3. Require `ex=3600` TTL on all `redis.set()` calls in code.
===
INCIDENT_ID: KAFKA-REBALANCE-404
CATEGORY: Apache Kafka
SEVERITY: HIGH
ERROR_CODE: CommitFailedException / group has already rebalanced
SYMPTOM: Consumers repeatedly log `CommitFailedException: Commit cannot be completed since the group has already rebalanced` and consumer lag spikes.
ROOT CAUSE: Processing a batch of messages (`max.poll.records`) took longer than `max.poll.interval.ms`, causing the broker coordinator to kick the consumer out of the group.
DIAGNOSTICS:
1. Check group rebalance state and lag: `kafka-consumer-groups.sh --bootstrap-server <broker:9092> --describe --group <group>`
REMEDIATION:
1. Decrease `max.poll.records` from `500` to `50` and increase `max.poll.interval.ms` to `600000` (10m).
2. Configure static membership via `group.instance.id`.
===
INCIDENT_ID: LINUX-EMFILE-024
CATEGORY: Linux Kernel / OS
SEVERITY: CRITICAL
ERROR_CODE: OSError: [Errno 24] Too many open files / socket() failed (24: Too many open files)
SYMPTOM: High-concurrency web servers or database workers fail to open new network sockets or files, throwing `OSError: [Errno 24] Too many open files`.
ROOT CAUSE: In Linux, every TCP socket, pipe, and disk file is a File Descriptor (FD). The process exhausted its per-process soft open-file limit (`ulimit -n`, which defaults to a tiny `1024` on many Linux distributions), or the application is leaking file handles/HTTP client sessions without using `with open(...)` context managers.
DIAGNOSTICS:
1. Count how many file descriptors the running PID currently has open:
   `ls -1 /proc/<PID>/fd | wc -l`
2. Inspect the hard and soft limits currently enforced on that running PID:
   `cat /proc/<PID>/limits | grep "Max open files"`
3. Identify what types of sockets/files are leaking:
   `lsof -p <PID> | awk '{print $5}' | sort | uniq -c | sort -nr`
REMEDIATION:
1. Raise the systemd service file descriptor ceiling in `/etc/systemd/system/app.service`:
   `[Service]`
   `LimitNOFILE=65535`
   Then run: `sudo systemctl daemon-reload && sudo systemctl restart app.service`
2. Reuse `requests.Session()` or `httpx.AsyncClient()` globally instead of instantiating a new client connection pool on every request.
===
INCIDENT_ID: LINUX-ENOSPC-INODES
CATEGORY: Linux Kernel / Filesystem
SEVERITY: CRITICAL
ERROR_CODE: OSError: [Errno 28] No space left on device (df -h shows free GBs available)
SYMPTOM: Services crash with `OSError: [Errno 28] No space left on device`, yet running `df -h` shows the disk is only 45% full with dozens of gigabytes free!
ROOT CAUSE: An ext4/XFS filesystem can run out of space in two ways: exhausting data blocks (`df -h`) OR exhausting **Inodes** (`df -i`). Every single file requires 1 inode. Millions of tiny 1KB files (like uncleaned `/tmp` session files, Docker overlay2 layers, or queued postfix/cron mail files in `/var/spool`) consume 100% of available inodes (`IUse% = 100%`).
DIAGNOSTICS:
1. Check filesystem Inode utilization (`IUse%`):
   `df -i`
2. Locate the exact directory containing millions of tiny files:
   `sudo find / -xdev -printf '%h
' | sort | uniq -c | sort -k 1 -n | tail -n 20`
REMEDIATION:
1. Delete millions of orphaned small files using `find ... -delete` (avoid `rm *`, which fails with `Argument list too long`):
   `sudo find /tmp -type f -mtime +2 -delete`
2. Prune dangling Docker container layers and build cache:
   `docker system prune -af --volumes`