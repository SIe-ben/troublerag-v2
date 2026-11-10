INCIDENT_ID: NGINX-UPSTREAM-502
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
3. Increase Nginx upstream read timeout in `nginx.conf`: `proxy_read_timeout 120s;`
===
INCIDENT_ID: NGINX-TIMEOUT-504
CATEGORY: Networking / Nginx
SEVERITY: HIGH
ERROR_CODE: HTTP 504 Gateway Time-out / upstream timed out (110: Connection timed out) while reading response header
SYMPTOM: Client requests hang for exactly 60 seconds and fail with `504 Gateway Time-out`. Nginx error log reports `upstream timed out (110: Connection timed out) while reading response header from upstream`.
ROOT CAUSE: Unlike 502 (where the connection was refused), 504 means Nginx successfully connected to the backend server, sent the request, and waited—but the backend took longer than `proxy_read_timeout` (default 60s) to return the first byte (due to slow database queries, synchronous LLM calls, or thread deadlock).
DIAGNOSTICS:
1. Measure direct backend latency bypassing Nginx using `curl` on localhost:
   `curl -w "Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s
" -o /dev/null -s http://127.0.0.1:8000/slow-endpoint`
2. Check active Nginx upstream timeout settings: `sudo nginx -T | grep -E "proxy_read_timeout|uwsgi_read_timeout"`
REMEDIATION:
1. Offload long-running tasks (>30s) to an asynchronous Celery/Redis background queue and return `HTTP 202 Accepted` with a job polling ID.
2. For legitimate long-streaming endpoints (like LLM token streaming), increase `proxy_read_timeout 300s;` and disable response buffering (`proxy_buffering off;`).
===
INCIDENT_ID: DNS-CORE-SERVFAIL
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
2. Deploy `NodeLocal DNSCache` as a DaemonSet so pods resolve DNS via a local node cache over TCP instead of flooding CoreDNS over UDP.
===
INCIDENT_ID: TLS-CERT-EXPIRED-526
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
2. Ensure Nginx points `ssl_certificate` to `fullchain.pem` (Leaf + Intermediate CA), never `cert.pem` alone.