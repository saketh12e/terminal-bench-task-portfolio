# Terminal Bench Task Portfolio

**Saketh Thumuluri**

A collection of terminal tasks covering systems debugging, scientific computing, data processing and machine learning. Each task includes its problem statement, container environment, reference solution and verifier.

## Terminal Bench 2.0

| Task | Type | What it involves |
| --- | --- | --- |
| [Event Feature Bundle](tasks/terminal-bench-2.0/event-feature-bundle) | Event-time processing and ML infrastructure | Repair causal revision selection, FIFO purchase/refund accounting, leakage-safe normalization and resumable feature generation. |
| [Retail Settlement ETL](tasks/terminal-bench-2.0/retail-settlement-etl) | Data engineering and financial reconciliation | Reconcile late corrections, split fulfillments, unit conversions, precise monetary allocations and row-level lineage. |
| [Language Router Audit](tasks/terminal-bench-2.0/language-router-audit) | NLP serving and evaluation | Align token scoring, request-time policy, calibration snapshots, predictions and serving-trace provenance through the installed CLI. |

## Terminal Bench 3.0

| Task | Type | What it involves |
| --- | --- | --- |
| [Python Linter Repair](tasks/terminal-bench-3.0/python-linter-repair) | Static analysis and developer tooling | Repair transitive rule activation, AST dispatch, corpus coverage and consistent finding fingerprints. |
| [ext4 Disk Recovery](tasks/terminal-bench-3.0/ext4-disk-recovery) | Filesystem forensics and binary repair | Reconstruct partition and backup-superblock geometry, preserve final disk bytes and align recovery reports with live binary probes. |
| [Physics Determinism](tasks/terminal-bench-3.0/physics-determinism) | Simulation and numerical debugging | Repair contact ordering, impulse accumulation, integration precision and deterministic comparison of simulated frames. |
| [Sparse Tensor Contraction](tasks/terminal-bench-3.0/sparse-tensor-contraction) | Native extensions and automatic differentiation | Repair a CPU C++/pybind11 pipeline across duplicate sparse-index coalescing, contraction results, backward gradients and runtime dispatch. |
| [Hyperparameter Equilibrium Atlas](tasks/terminal-bench-3.0/hyperparameter-equilibrium-atlas) | ML optimization and mathematical certification | Construct complete teacher-feedback equilibrium branches, compute sensitivities and allocate continuous curricula under shared resource budgets. |
| [Robust Label Audit](tasks/terminal-bench-3.0/robust-label-audit) | Robust ML evaluation and optimization | Certify conditional evaluation metrics and integer policy allocation under correlated calibration and population uncertainty. |

## Terminal Bench 4.0

| Task | Type | What it involves |
| --- | --- | --- |
| [Adaptive MHD Restart](tasks/terminal-bench-4.0/adaptive-mhd-restart) | Scientific computing and checkpoint recovery | Preserve conservation, magnetic-flux continuity and restart equivalence across mesh changes, nested subcycles and ownership transfers. |
| [Incremental Build Coordinator](tasks/terminal-bench-4.0/incremental-build-coordinator) | Build systems and durable state | Repair discovered dependencies, semantic cache reuse, receipt replay, crash recovery and atomic artifact publication. |
| [Speech Graph Gradients](tasks/terminal-bench-4.0/speech-graph-gradients) | Speech training and numerical differentiation | Preserve weighted graph-path multiplicity, silent-cycle behavior, shared gradients and joint Hessian-vector products. |

## Task pairs

| Focus | Paired tasks |
| --- | --- |
| Restart and durable state | Adaptive MHD Restart + Incremental Build Coordinator |
| Event time and accounting | Event Feature Bundle + Retail Settlement ETL |
| Executable-path correctness | Language Router Audit + Python Linter Repair |
| Numerical derivatives | Speech Graph Gradients + Sparse Tensor Contraction |
| Final-artifact integrity | ext4 Disk Recovery + Physics Determinism |
| Mathematical certificates | Hyperparameter Equilibrium Atlas + Robust Label Audit |

## Task layout

- `instruction.md` describes the problem and deliverables.
- `task.toml` defines the task and runtime requirements.
- `environment/` contains the starter implementation and public inputs.
- `solution/` contains the reference implementation.
- `tests/` contains the verifier and its fixtures.
