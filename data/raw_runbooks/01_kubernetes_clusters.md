INCIDENT_ID: K8S-OOM-137
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
3. For Java/JVM apps, enable container support: `java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar`
===
INCIDENT_ID: K8S-IMAGEPULL-401
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
   `kubectl patch serviceaccount default -n <namespace> -p '{"imagePullSecrets": [{"name": "regcred"}]}'`
===
INCIDENT_ID: K8S-CRASHLOOP-001
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
2. Increase `timeoutSeconds` on `livenessProbe` from default `1s` to `5s` so brief GC pauses do not trigger full container restarts.
===
INCIDENT_ID: K8S-PV-MOUNT-204
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
2. If concurrent multi-node access is required, migrate storage class to an NFS/EFS `ReadWriteMany` (RWX) provisioner.