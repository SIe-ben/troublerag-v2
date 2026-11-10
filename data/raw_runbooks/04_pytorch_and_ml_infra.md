INCIDENT_ID: CUDA-VRAM-001
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
3. Defragment allocator: `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
===
INCIDENT_ID: NCCL-DDP-TIMEOUT
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
3. If Shared Memory P2P fails on PCIe topologies, set `export NCCL_P2P_DISABLE=1`.
===
INCIDENT_ID: CUDA-DEVICE-ASSERT-059
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
2. Check for `NaN` or `Inf` values in input features that corrupt probability distributions inside `torch.multinomial` or `BCELoss`: `torch.isnan(inputs).any()`.