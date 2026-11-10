import os
import re
import requests

OUTPUT_DIR = "data/raw_runbooks"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# PART 1: Multi-File Enterprise Runbook Corpus (Organized by Domain)

DOMAIN_FILES = {
    "01_kubernetes_clusters.md": [
        """INCIDENT_ID: K8S-OOM-137
CATEGORY: Kubernetes
SEVERITY: CRITICAL
ERROR_CODE: ExitCode 137 / SIGKILL / OOMKilled
SYMPTOM: Pod enters CrashLoopBackOff after terminating with ExitCode 137. Node dmesg shows: Memory cgroup out of memory: Killed process (python3).
ROOT CAUSE: Container Resident Set Size (RSS) crossed the hard cgroup limit defined in resources.limits.memory, triggering the Linux kernel OOM killer (SIGKILL 128+9).
DIAGNOSTICS:
1. Check pod termination state: `kubectl get pod <pod> -n <ns> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'`
2. Inspect host kernel OOM logs: `dmesg -T | grep -i -E 'oom|killed process'`
3. Check real-time container memory: `kubectl top pod <pod> -n <ns> --containers`
REMEDIATION:
1. Raise memory limits in deployment YAML: `kubectl set resources deployment/<name> -c=<container> --limits=memory=4Gi --requests=memory=2Gi`
2. Recycle Gunicorn workers to prevent slow leaks: `gunicorn app:app --max-requests 1000 --max-requests-jitter 100`
3. For Java/JVM apps, enable container support: `java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar`""",

        """INCIDENT_ID: K8S-IMAGEPULL-401
CATEGORY: Kubernetes
SEVERITY: HIGH
ERROR_CODE: ErrImagePull / ImagePullBackOff / unauthorized: authentication required
SYMPTOM: New Pod replicas stay stuck in Pending state with status `ImagePullBackOff`. Running `kubectl describe pod` shows `Failed to pull image: rpc error: code = Unknown desc = unauthorized: authentication required` or `manifest for <image>:<tag> not found`.
ROOT CAUSE: The kubelet on the worker node lacks valid Docker registry credentials (`imagePullSecrets`), the registry token expired, or the CI/CD pipeline pushed a non-existent image tag.
DIAGNOSTICS:
1. Inspect exact kubelet pull error: `kubectl describe pod <pod-name> -n <namespace> | grep -A 10 Events:`
2. Verify existing registry secrets in the namespace: `kubectl get secrets -n <namespace> --field-selector type=kubernetes.io/dockerconfigjson`
3. Decode and verify secret payload: `kubectl get secret regcred -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 --decode`
REMEDIATION:
1. Recreate the Docker registry secret with fresh credentials:
   `kubectl create secret docker-registry regcred --docker-server=<registry-url> --docker-username=<user> --docker-password=<token> -n <namespace>`
2. Attach `imagePullSecrets: [{name: regcred}]` to the Pod spec or patch the default ServiceAccount:
   `kubectl patch serviceaccount default -n <namespace> -p '{"imagePullSecrets": [{"name": "regcred"}]}'`""",

        """INCIDENT_ID: K8S-CRASHLOOP-001
CATEGORY: Kubernetes
SEVERITY: CRITICAL
ERROR_CODE: CrashLoopBackOff / Liveness probe failed: HTTP probe failed with statuscode: 500
SYMPTOM: Container starts, runs for 30-60 seconds, gets restarted repeatedly by kubelet, and enters `CrashLoopBackOff`. Events show `Liveness probe failed: Get "http://10.244.1.45:8080/healthz": context deadline exceeded (Client.Timeout exceeded while awaiting headers)`.
ROOT CAUSE: Either the application entrypoint script is crashing due to a missing environment variable/ConfigMap, OR the `livenessProbe` initialDelaySeconds is shorter than the application's cold-start initialization time (e.g., loading ML weights into RAM).
DIAGNOSTICS:
1. Fetch logs from the PREVIOUS crashed container instance (crucial flag `--previous`):
   `kubectl logs <pod-name> -n <namespace> --previous --tail=100`
2. Inspect probe thresholds and timeouts:
   `kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A 15 livenessProbe:`
REMEDIATION:
1. Add a `startupProbe` to protect slow-starting applications (like ML models or JVM services) from premature liveness kills:
   `startupProbe: {httpGet: {path: /healthz, port: 8080}, failureThreshold: 30, periodSeconds: 10}`
2. Increase `timeoutSeconds` on `livenessProbe` from default `1s` to `5s` so brief GC pauses do not trigger full container restarts.""",

        """INCIDENT_ID: K8S-PV-MOUNT-204
CATEGORY: Kubernetes
SEVERITY: HIGH
ERROR_CODE: Multi-Attach error for volume / Unable to attach or mount volumes: unmounted volumes
SYMPTOM: Rolling deployment hangs; new Pod stays stuck in `ContainerCreating` while old Pod is terminating. Event log reports `Multi-Attach error for volume "pvc-8a9b1c" Volume is already exclusively attached to one node and can't be attached to another`.
ROOT CAUSE: The PersistentVolumeClaim (PVC) uses `ReadWriteOnce` (RWO) block storage (such as AWS EBS or Azure Disk), which can only be mounted by a single physical worker node at a time. During a `RollingUpdate`, Kubernetes scheduled the new Pod onto Node B before the old Pod on Node A detached the volume.
DIAGNOSTICS:
1. Check VolumeAttachment objects across the cluster: `kubectl get volumeattachment`
2. Inspect PVC access modes (`ReadWriteOnce` vs `ReadWriteMany`): `kubectl get pvc -n <namespace>`
REMEDIATION:
1. Change Deployment strategy from `RollingUpdate` to `Recreate` in the deployment manifest so the old Pod terminates and detaches storage before the new Pod starts:
   `spec: {strategy: {type: Recreate}}`
2. If concurrent multi-node access is required, migrate storage class to an NFS/EFS `ReadWriteMany` (RWX) provisioner."""
    ],

    "02_postgresql_databases.md": [
        """INCIDENT_ID: PG-POOL-53300
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
3. Deploy PgBouncer in `pool_mode = transaction`.""",

        """INCIDENT_ID: PG-DEADLOCK-40P01
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
2. Keep transactions short and never perform external HTTP calls inside an open `BEGIN ... COMMIT` block.""",

        """INCIDENT_ID: PG-WAL-DISK-53100
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
3. Set `max_slot_wal_keep_size = 10GB` in `postgresql.conf` to prevent any dead replica from crashing the primary disk in the future.""",

        """INCIDENT_ID: PG-XID-WRAPAROUND-22000
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
   `ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 2000; SELECT pg_reload_conf();`"""
    ],

    "03_networking_and_tls.md": [
        """INCIDENT_ID: NGINX-UPSTREAM-502
CATEGORY: Networking / Nginx
SEVERITY: CRITICAL
ERROR_CODE: HTTP 502 Bad Gateway / connect() failed (111: Connection refused) while connecting to upstream
SYMPTOM: Nginx returns 502 Bad Gateway; error.log reports `connect() failed (111: Connection refused) while connecting to upstream http://127.0.0.1:8000`.
ROOT CAUSE: Backend application server (Gunicorn/Uvicorn/FastAPI) is stopped, crashed, bound to the wrong interface, or kernel TCP listen backlog (`somaxconn`) is overflowing.
DIAGNOSTICS:
1. Check upstream service status: `sudo systemctl status gunicorn.service`
2. Verify listening TCP sockets: `sudo ss -tulpn | grep 8000`
3. Check kernel listen queue drops: `netstat -s | grep -i listen`
REMEDIATION:
1. Restart upstream service and verify port binding: `sudo systemctl restart gunicorn.service`
2. Fix Unix socket permissions if using `.sock`: `sudo chown www-data:www-data /run/gunicorn.sock && sudo chmod 660 /run/gunicorn.sock`
3. Increase Nginx upstream read timeout in `nginx.conf`: `proxy_read_timeout 120s;`""",

        """INCIDENT_ID: NGINX-TIMEOUT-504
CATEGORY: Networking / Nginx
SEVERITY: HIGH
ERROR_CODE: HTTP 504 Gateway Time-out / upstream timed out (110: Connection timed out) while reading response header
SYMPTOM: Client requests hang for exactly 60 seconds and fail with `504 Gateway Time-out`. Nginx error log reports `upstream timed out (110: Connection timed out) while reading response header from upstream`.
ROOT CAUSE: Unlike 502 (where the connection was refused), 504 means Nginx successfully connected to the backend server, sent the request, and waited—but the backend took longer than `proxy_read_timeout` (default 60s) to return the first byte (due to slow database queries, synchronous LLM calls, or thread deadlock).
DIAGNOSTICS:
1. Measure direct backend latency bypassing Nginx using `curl` on localhost:
   `curl -w "Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" -o /dev/null -s http://127.0.0.1:8000/slow-endpoint`
2. Check active Nginx upstream timeout settings: `sudo nginx -T | grep -E "proxy_read_timeout|uwsgi_read_timeout"`
REMEDIATION:
1. Offload long-running tasks (>30s) to an asynchronous Celery/Redis background queue and return `HTTP 202 Accepted` with a job polling ID.
2. For legitimate long-streaming endpoints (like LLM token streaming), increase `proxy_read_timeout 300s;` and disable response buffering (`proxy_buffering off;`).""",

        """INCIDENT_ID: DNS-CORE-SERVFAIL
CATEGORY: Networking / DNS
SEVERITY: CRITICAL
ERROR_CODE: Temporary failure in name resolution / gaierror: [Errno -3] / RCODE: SERVFAIL
SYMPTOM: Microservices fail to connect to internal or external hostnames with `socket.gaierror: [Errno -3] Temporary failure in name resolution` or `dial tcp: lookup db.internal.svc.cluster.local on 10.96.0.10:53: read udp: i/o timeout`.
ROOT CAUSE: Either CoreDNS pods in the cluster are throttled/OOM-killed, the Linux conntrack UDP table is full, or Alpine/glibc `ndots:5` configuration in `/etc/resolv.conf` is multiplying every external DNS query by 5 search-path lookups before querying the root domain.
DIAGNOSTICS:
1. Test direct DNS resolution against the CoreDNS cluster IP:
   `dig @10.96.0.10 db.internal.svc.cluster.local +stats`
2. Inspect `/etc/resolv.conf` inside the failing container: `cat /etc/resolv.conf`
3. Check CoreDNS pod logs for upstream forwarder timeouts: `kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100`
REMEDIATION:
1. Lower `ndots` from `5` to `2` in the Pod `dnsConfig` spec to reduce DNS query amplification by 60%:
   `dnsConfig: {options: [{name: ndots, value: "2"}, {name: timeout, value: "2"}]}`
2. Deploy `NodeLocal DNSCache` as a DaemonSet so pods resolve DNS via a local node cache over TCP instead of flooding CoreDNS over UDP.""",

        """INCIDENT_ID: TLS-CERT-EXPIRED-526
CATEGORY: Networking / Security TLS
SEVERITY: CRITICAL
ERROR_CODE: SSL_ERROR_RX_RECORD_TOO_LONG / x509: certificate has expired or is not yet valid / SSLCertVerificationError
SYMPTOM: HTTPS API calls fail immediately with `ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired` or `unable to get local issuer certificate`.
ROOT CAUSE: Either the leaf X.509 TLS certificate passed its `NotAfter` timestamp because `cert-manager` failed its Let's Encrypt ACME HTTP-01 challenge, OR the server is serving only the leaf certificate (`cert.pem`) instead of the full certificate chain (`fullchain.pem` including the intermediate CA).
DIAGNOSTICS:
1. Inspect the live certificate expiration dates and intermediate chain directly from the socket:
   `echo | openssl s_client -servername api.example.com -connect api.example.com:443 2>/dev/null | openssl x509 -noout -dates -issuer -subject`
2. Verify whether the full intermediate chain is sent:
   `openssl s_client -connect api.example.com:443 -showcerts`
REMEDIATION:
1. Force renewal via Certbot or cert-manager:
   `sudo certbot renew --force-renewal && sudo systemctl reload nginx`
2. Ensure Nginx points `ssl_certificate` to `fullchain.pem` (Leaf + Intermediate CA), never `cert.pem` alone."""
    ],

    "04_pytorch_and_ml_infra.md": [
        """INCIDENT_ID: CUDA-VRAM-001
CATEGORY: PyTorch / GPU
SEVERITY: HIGH
ERROR_CODE: RuntimeError: CUDA out of memory / CUDACachingAllocator
SYMPTOM: Training or inference crashes with `RuntimeError: CUDA out of memory. Tried to allocate 512.00 MiB`.
ROOT CAUSE: Forward-pass activation tensors, excessive `batch_size`, un-detached loss logging (`total_loss += loss`), or `CUDACachingAllocator` memory fragmentation exceeded physical GPU VRAM.
DIAGNOSTICS:
1. Check live GPU process usage: `nvidia-smi`
2. Inspect PyTorch memory block fragmentation: `print(torch.cuda.memory_summary())`
REMEDIATION:
1. Detach metrics during logging: Use `loss.item()` instead of keeping tensor references.
2. Enable mixed precision (`torch.cuda.amp.autocast(dtype=torch.float16)`) and gradient accumulation.
3. Defragment allocator: `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`""",

        """INCIDENT_ID: NCCL-DDP-TIMEOUT
CATEGORY: PyTorch / Distributed GPU
SEVERITY: CRITICAL
ERROR_CODE: ProcessGroupNCCL.cpp:Watchdog caught collective operation timeout / NCCL WARN Socket recv failed
SYMPTOM: Multi-GPU DistributedDataParallel (DDP) training hangs and crashes after 1800 seconds with `RuntimeError: [Rank 2] Watchdog caught collective operation timeout: WorkNCCL(OpType=ALLREDUCE) ran for 1800082 milliseconds before timing out`.
ROOT CAUSE: One GPU worker rank stalled during data loading, checkpoint saving (where Rank 0 writes to disk while Ranks 1..N already entered the next `AllReduce` barrier), or shared memory (`/dev/shm`) inside the Docker container defaulted to 64MB, breaking NCCL inter-process communication.
DIAGNOSTICS:
1. Re-run training with NCCL debug logging enabled to see exact socket/IB transport failures:
   `export NCCL_DEBUG=INFO; export TORCH_DISTRIBUTED_DEBUG=DETAIL`
2. Check Docker shared memory size inside the container: `df -h /dev/shm`
REMEDIATION:
1. Pass `--shm-size=16g` (or `--ipc=host`) to `docker run` / Kubernetes `emptyDir: {medium: Memory}` so NCCL & DataLoader workers do not exhaust `/dev/shm`.
2. Add `dist.barrier()` immediately after Rank-0-only operations (like model checkpointing or evaluation) so other ranks do not desynchronize.
3. If Shared Memory P2P fails on PCIe topologies, set `export NCCL_P2P_DISABLE=1`.""",

        """INCIDENT_ID: CUDA-DEVICE-ASSERT-059
CATEGORY: PyTorch / GPU
SEVERITY: HIGH
ERROR_CODE: RuntimeError: CUDA error: device-side assert triggered / cublasRuntimeError
SYMPTOM: PyTorch crashes with `RuntimeError: CUDA error: device-side assert triggered`. The Python stack trace points to an unrelated line (such as `.to(device)` or `loss.item()`) because CUDA kernel execution is asynchronous.
ROOT CAUSE: An out-of-bounds index occurred inside a GPU kernel—almost always caused by passing a target class label into `nn.CrossEntropyLoss()` that is negative (`< 0`) or greater than/equal to `num_classes` (`>= C`), or passing token IDs into `nn.Embedding(vocab_size, dim)` that exceed `vocab_size - 1`.
DIAGNOSTICS:
1. Force synchronous CUDA execution so the stack trace points to the EXACT failing line of Python code:
   `CUDA_LAUNCH_BLOCKING=1 python train.py`
2. Validate label tensor min/max values on CPU before moving to GPU:
   `assert labels.min() >= 0 and labels.max() < num_classes, f"Invalid label range: {labels.min()} to {labels.max()}"`
REMEDIATION:
1. Audit dataset class mapping (`0` to `num_classes - 1`)—remember PyTorch `CrossEntropyLoss` expects 0-indexed integer labels, not 1-indexed labels.
2. Check for `NaN` or `Inf` values in input features that corrupt probability distributions inside `torch.multinomial` or `BCELoss`: `torch.isnan(inputs).any()`."""
    ],

    "05_redis_kafka_linux.md": [
        """INCIDENT_ID: REDIS-OOM-099
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
3. Require `ex=3600` TTL on all `redis.set()` calls in code.""",

        """INCIDENT_ID: KAFKA-REBALANCE-404
CATEGORY: Apache Kafka
SEVERITY: HIGH
ERROR_CODE: CommitFailedException / group has already rebalanced
SYMPTOM: Consumers repeatedly log `CommitFailedException: Commit cannot be completed since the group has already rebalanced` and consumer lag spikes.
ROOT CAUSE: Processing a batch of messages (`max.poll.records`) took longer than `max.poll.interval.ms`, causing the broker coordinator to kick the consumer out of the group.
DIAGNOSTICS:
1. Check group rebalance state and lag: `kafka-consumer-groups.sh --bootstrap-server <broker:9092> --describe --group <group>`
REMEDIATION:
1. Decrease `max.poll.records` from `500` to `50` and increase `max.poll.interval.ms` to `600000` (10m).
2. Configure static membership via `group.instance.id`.""",

        """INCIDENT_ID: LINUX-EMFILE-024
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
2. Reuse `requests.Session()` or `httpx.AsyncClient()` globally instead of instantiating a new client connection pool on every request.""",

        """INCIDENT_ID: LINUX-ENOSPC-INODES
CATEGORY: Linux Kernel / Filesystem
SEVERITY: CRITICAL
ERROR_CODE: OSError: [Errno 28] No space left on device (df -h shows free GBs available)
SYMPTOM: Services crash with `OSError: [Errno 28] No space left on device`, yet running `df -h` shows the disk is only 45% full with dozens of gigabytes free!
ROOT CAUSE: An ext4/XFS filesystem can run out of space in two ways: exhausting data blocks (`df -h`) OR exhausting **Inodes** (`df -i`). Every single file requires 1 inode. Millions of tiny 1KB files (like uncleaned `/tmp` session files, Docker overlay2 layers, or queued postfix/cron mail files in `/var/spool`) consume 100% of available inodes (`IUse% = 100%`).
DIAGNOSTICS:
1. Check filesystem Inode utilization (`IUse%`):
   `df -i`
2. Locate the exact directory containing millions of tiny files:
   `sudo find / -xdev -printf '%h\n' | sort | uniq -c | sort -k 1 -n | tail -n 20`
REMEDIATION:
1. Delete millions of orphaned small files using `find ... -delete` (avoid `rm *`, which fails with `Argument list too long`):
   `sudo find /tmp -type f -mtime +2 -delete`
2. Prune dangling Docker container layers and build cache:
   `docker system prune -af --volumes`"""
    ]
}

def write_domain_files():
    total_incidents = 0
    for filename, incident_list in DOMAIN_FILES.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        content = "\n===\n".join(incident_list)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        total_incidents += len(incident_list)
        print(f"📁 Created {filename} ({len(incident_list)} enterprise runbooks)")
    return total_incidents


# PART 2: Live Open-Source GitHub Runbook Fetcher

GITHUB_RAW_URLS = [
    ("K8S-NODE-NOT-READY", "Kubernetes", "HIGH", "KubeNodeNotReady",
     "https://raw.githubusercontent.com/prometheus-operator/runbooks/main/content/runbooks/kubernetes/KubeNodeNotReady.md"),
    ("K8S-POD-CRASHLOOP", "Kubernetes", "CRITICAL", "KubePodCrashLooping",
     "https://raw.githubusercontent.com/prometheus-operator/runbooks/main/content/runbooks/kubernetes/KubePodCrashLooping.md"),
    ("K8S-MEMORY-OVERCOMMIT", "Kubernetes", "MEDIUM", "KubeMemoryOvercommit",
     "https://raw.githubusercontent.com/prometheus-operator/runbooks/main/content/runbooks/kubernetes/KubeMemoryOvercommit.md"),
    ("HOST-OOM-KILL", "Linux Kernel / OS", "HIGH", "NodeOOMKillDetected",
     "https://raw.githubusercontent.com/prometheus-operator/runbooks/main/content/runbooks/node/NodeOOMKillDetected.md"),
    ("HOST-FILESYSTEM-FULL", "Linux Kernel / Filesystem", "CRITICAL", "NodeFilesystemAlmostOutOfSpace",
     "https://raw.githubusercontent.com/prometheus-operator/runbooks/main/content/runbooks/node/NodeFilesystemAlmostOutOfSpace.md"),
]

def fetch_github_runbooks():
    fetched_blocks = []
    print("\n🌐 Fetching live open-source Prometheus/Kubernetes runbooks from GitHub...")
    for inc_id, category, severity, err_code, url in GITHUB_RAW_URLS:
        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                # Strip Hugo YAML frontmatter (--- ... ---)
                clean_md = re.sub(r"^---.*?---\s*", "", resp.text, flags=re.DOTALL).strip()
                formatted_block = (
                    f"INCIDENT_ID: {inc_id}\n"
                    f"CATEGORY: {category}\n"
                    f"SEVERITY: {severity}\n"
                    f"ERROR_CODE: {err_code}\n"
                    f"{clean_md}"
                )
                fetched_blocks.append(formatted_block)
                print(f"   ✓ Downloaded & normalized: {inc_id} ({err_code})")
        except Exception as e:
            print(f"   ⚠️ Skipped {inc_id} (Offline/Timeout): {e}")

    if fetched_blocks:
        gh_file = os.path.join(OUTPUT_DIR, "06_github_prometheus_runbooks.md")
        with open(gh_file, "w", encoding="utf-8") as f:
            f.write("\n===\n".join(fetched_blocks))
        print(f"📁 Created 06_github_prometheus_runbooks.md ({len(fetched_blocks)} live GitHub runbooks)")
    return len(fetched_blocks)

if __name__ == "__main__":
    # Remove old starter file if it exists so we don't duplicate
    old_file = os.path.join(OUTPUT_DIR, "core_infrastructure.md")
    if os.path.exists(old_file):
        os.remove(old_file)

    local_count = write_domain_files()
    gh_count = fetch_github_runbooks()
    print(f"\n🎉 Corpus Build Complete! Total Distinct Incidents: {local_count + gh_count} across 6 Markdown files.")