INCIDENT_ID: K8S-NODE-NOT-READY
CATEGORY: Kubernetes
SEVERITY: HIGH
ERROR_CODE: KubeNodeNotReady
# KubeNodeNotReady

## Meaning

KubeNodeNotReady alert is fired when a Kubernetes node is not in `Ready`
state for a certain period. In this case, the node is not able to host any new
pods as described [here][KubeNode].

## Impact

The performance of the cluster deployments is affected, depending on the overall
workload and the type of the node.

## Diagnosis

The notification details should list the node that's not ready. For Example:

```txt
 - alertname = KubeNodeNotReady
...
 - node = node1.example.com
...
```

Login to the cluster. Check the status of that node:

```shell
$ kubectl get node $NODE -o yaml
```

The output should describe why the node isn't ready (e.g.: timeouts reaching the
API or kubelet).

## Mitigation

Once, the problem was resolved that prevented node from being replaced,
the instance should be terminated.

See [KubeNode](https://kubernetes.io/docs/concepts/architecture/nodes/#condition)
See [node problem detector](https://github.com/kubernetes/node-problem-detector)
===
INCIDENT_ID: K8S-POD-CRASHLOOP
CATEGORY: Kubernetes
SEVERITY: CRITICAL
ERROR_CODE: KubePodCrashLooping
# KubePodCrashLooping

## Meaning

Pod is in CrashLoop which means the app dies or is unresponsive and 
kubernetes tries to restart it automatically.

## Impact

Service degradation or unavailability.
Inability to do rolling upgrades.
Certain apps will not perform required tasks such as data migrations.

## Diagnosis

- Check template via `kubectl -n $NAMESPACE get pod $POD`.
- Check pod events via `kubectl -n $NAMESPACE describe pod $POD`.
- Check pod logs via `kubectl -n $NAMESPACE logs $POD -c $CONTAINER`
- Check pod template parameters such as:
  - pod priority
  - resources - maybe it tries to use unavailable resource, such as GPU but
    there is limited number of nodes with GPU
  - readiness and liveness probes may be incorrect - wrong port or command,
    check is failing too fast due to short timeout for response

Other things to check:

- app responding extremely slow due to resource constraints such as memory too
  low, not enough CPU which is required on start
- app waits for other services to start, such as database
- misconfiguration causing app crash on start
- missing files such as configmaps/secrets/volumes
- read only filesystem
- wrong user permissions in container
- lack of special container capabilities (securityContext)
- app is executed in different directory than expected
  (for example WORKDIR from Docerkfile is not used in OpenShift)

## Mitigation

Talk with developers or read documentation about the app, ensure to define
sane default values to start the app.

See [Debugging Pods](https://kubernetes.io/docs/tasks/debug-application-cluster/debug-application/#debugging-pods)
===
INCIDENT_ID: K8S-MEMORY-OVERCOMMIT
CATEGORY: Kubernetes
SEVERITY: MEDIUM
ERROR_CODE: KubeMemoryOvercommit
# KubeMemoryOvercommit

## Meaning

Cluster has overcommitted Memory resource requests for Pods
and cannot tolerate node failure.

<details>
<summary>Full context</summary>

Total number of Memory requests for pods exceeds cluster capacity.
In case of node failure some pods will not fit in the remaining nodes.

</details>

## Impact

The cluster cannot tolerate node failure. In the event of a node failure,
some Pods will be in `Pending` state.

## Diagnosis

- Check if Memory resource requests are adjusted to the app usage
- Check if some nodes are available and not cordoned
- Check if cluster-autoscaler has issues with adding new nodes

## Mitigation

- Add more nodes to the cluster - usually it is better to have more smaller
  nodes, than few bigger.

- Add different node pools with different instance types to avoid problem
  when using only one instance type in the cloud.

- Use pod priorities to avoid important services from losing performance,
  see [pod priority and preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)

- Fine tune settings for special pods used with [cluster-autoscaler](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md#how-does-cluster-autoscaler-work-with-pod-priority-and-preemption)

- Prepare performance tests for the expected workload, plan cluster capacity
  accordingly.
===
INCIDENT_ID: HOST-FILESYSTEM-FULL
CATEGORY: Linux Kernel / Filesystem
SEVERITY: CRITICAL
ERROR_CODE: NodeFilesystemAlmostOutOfSpace
# NodeFilesystemAlmostOutOfSpace

## Meaning

This alert is similar to the NodeFilesystemSpaceFillingUp alert, but rather
than being based on a prediction that a filesystem will become full in a certain
amount of time, it uses simple static thresholds. The alert will fire as at a
`warning` level at 5% space left, and at a `critical` level with 3% space left.

## Impact

A node's filesystem becoming full can have a far reaching impact, as it may
cause any or all of the applications scheduled to that node to experience
anything from performance degradation to full inoperability. Depending on the
node and filesystem involved, this could pose a critical threat to the stability
of the cluster.

## Diagnosis

## Mitigation

See [Node Filesystem FilesFilling Up]({{< ref "./NodeFilesystemFilesFillingUp.md" >}})