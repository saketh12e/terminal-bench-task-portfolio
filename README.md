# Terminal task portfolio

**Saketh Thumuluri — 12 selected terminal-agent tasks, organized into six pairs.**

The collection covers systems debugging, scientific computing, release-path correctness, event-time data processing and mathematical ML evaluation. Each task includes its problem statement, container environment, reference solution and verifier. Model rollouts, authoring ledgers and evaluation archives are excluded.

The source workstreams span **Dynamo / Terminal-Bench 2.0**, **Pluto / Terminal-Bench 3.0**, **Insight**, **Thanos**, and a **Terminal-Bench 4 candidate**. The original [AMR task README](tasks/thanos/amr-mhd-restart/README.md#relevant-experience) records the Dynamo/TB2 and Pluto/TB3 associations. These labels describe authoring workstreams; official benchmark-release membership has not been independently established.

Start with **AMR/MHD restart** for the strongest measured model challenge, **feature-bundle repair** for temporal data correctness, or **ext4 recovery** for a compact terminal debugging example.

## Selected tasks

Solve counts below are **full-task successes**, not percentages of individual tests passed. **Measured** means saved result artifacts were reviewed for the selected revision. **Recorded** means the figures come from prior project completion notes. **Local** describes correctness checks rather than fresh model calibration. All results are historical; publication did not launch new trials.

| Task | Workstream | Difficulty / calibration stamp |
| --- | --- | --- |
| [Adaptive MHD restart](tasks/thanos/amr-mhd-restart) | Thanos; accepted package v5 | **Measured high difficulty:** `tencent/hy4-preview`, high reasoning, Claude Code: **0/8** selected full-credit solves. Two provider-error attempts excluded. Local reference **85/85**. |
| [Closure Build](tasks/tb4/closure-build) | TB4 systems candidate; task v6.0.0 | **Uncalibrated systems sample:** local reference **513/513**; untouched starter **107/513**, reward 0. No v6 solver solve rate. |
| [Feature-bundle repair](tasks/dynamo/repair-feature-bundle) | Dynamo / TB2 workstream | **Measured:** DeepSeek V4 Pro **0/5** solves: **four completed semantic failures**, one runtime-only failure; no timeouts. Historical Oracle reward 1 / NOP 0. |
| [Settlement ETL](tasks/dynamo/settlement-etl) | Dynamo / TB2 workstream | **Recorded:** **0/5** solves; four valid failures and one soft timeout. The timeout is excluded from analytical difficulty. |
| [Router score audit](tasks/dynamo/router-score-audit) | Dynamo / TB2 workstream | **Recorded:** **1/5** solves and four valid failures. Trial-model identity was not independently recovered. |
| [Custom linter regression](tasks/pluto/custom-linter-rule-regression-repair) | Pluto / TB3 workstream | **Recorded high difficulty:** Sonnet 4.6 **0/5**, Opus 4.7 **1/8** solves; **90 tests**. |
| [Speech graph gradients](tasks/thanos/speech-graph-gradients) | Thanos; revision-3-ready | **Local numerical sample:** reference and independent alternative **647/647**. Three historical implementations fail 14 new cases each, **42/42 case replays**, with no timeouts. Fresh-agent calibration unmeasured. |
| [Sparse tensor contraction](tasks/pluto/repair-custom-sparse-tensor-contraction-extension-repair) | Pluto / TB3 workstream | **Recorded:** Sonnet 4.6 **1/5**, Opus 4.7 **5/8** solves; **81 tests**. |
| [ext4 forensic geometry](tasks/pluto/ext4-forensic-geometry-repair) | Pluto / TB3 workstream | **Recorded high difficulty:** Sonnet 4.6 **0/5**, Opus 4.7 **1/8** solves; **83 tests**. |
| [Physics determinism](tasks/pluto/openmp-physics-determinism-repair) | Pluto / TB3 workstream | **Recorded high difficulty:** Sonnet 4.6 **0/5**, Opus 4.7 **2/8** solves; **71 tests**. The supplied implementation is Python despite the original OpenMP slug. |
| [Hyperparameter Atlas](tasks/insight/hyperparameter-atlas) | Insight | **Measured:** GPT-5.6 Sol **0/5** solves, no trial exceptions; includes one numerical endpoint near miss. Historical Oracle **82/82**, NOP reward 0. |
| [Joint Label Audit](tasks/insight/joint-label-audit) | Insight | **Measured:** GPT-5.6 Sol **2/5** solves. Of three nonpasses, one is a substantive regret discrepancy and two are simplex-rounding rejections. Passing agent artifacts **88/88**. |

## Six task pairs

1. **Restart and durable state — AMR/MHD + Closure Build.** The MHD task couples conserved cell quantities, magnetic faces, recursive time subcycles and checkpoint receipts. Closure Build couples dependency discovery, semantic cache identity, receipt replay, content-addressed storage and atomic publication. Both require equivalence across interruption and recovery.

2. **Event time and accounting — Feature Bundle + Settlement ETL.** Feature Bundle combines causal revisions, full-history FIFO settlement, window projections, fold-disjoint normalization and resumable checkpoints. Settlement ETL combines late overrides, split fulfillments, signed Decimal residual allocation and row-level lineage. Plausible aggregate outputs do not establish correct event selection or provenance.

3. **Repair the executing path — Router Audit + Custom Linter.** Router Audit requires agreement between the installed CLI, helper API, request-time policy, calibration and token-level lineage. The linter requires transitive rule activation, AST dispatch, corpus expansion and finding fingerprints to agree with the actual scan. Fixing an isolated helper leaves the deployed path wrong.

4. **Numerical derivatives — Speech Graphs + Sparse Contraction.** Speech Graphs requires path multiplicity, both-sided epsilon moves, convergent silent cycles, shared parameters and mixed Hessian-vector products. Sparse Contraction joins a CPU C++/pybind11 extension with duplicate-COO coalescing, backward gradients and live policy dispatch. Forward plausibility alone is insufficient.

5. **Inspect the final artifact — ext4 Recovery + Physics Determinism.** ext4 Recovery repairs binary partition and backup-superblock geometry while a late finalizer can undo an earlier repair. Its reports and trace digests must match final disk bytes. Physics Determinism checks contact ordering, impulse reduction, integration precision and complete twin-run comparison against live frame digests.

6. **Complete mathematical certificates — Hyperparameter Atlas + Joint Label Audit.** Atlas requires all relevant equilibrium sheets, branch sensitivities and globally coupled continuous curricula. Joint Label Audit requires shared calibration and population uncertainty to support robust integer policy allocation and a global regret certificate. These are advanced evaluation samples; the numerical rejection caveats in the table are part of their calibration interpretation.

## Inspect or run a task

Within each task directory:

- `instruction.md` gives the agent-facing problem and deliverables.
- `task.toml` records the runtime, schema and resource contract.
- `environment/` contains the starter implementation and public inputs.
- `solution/` contains the reference repair.
- `tests/` contains the verifier and required fixtures.

Use a Linux Docker environment and a Harbor version compatible with the selected task's `schema_version`. The Insight packages record Harbor 0.18.0; this collection preserves the original task schemas and runtime definitions.

For example, from this repository root:

```bash
harbor run --path tasks/thanos/amr-mhd-restart --agent oracle --env docker --jobs-dir /tmp/terminal-portfolio-oracle
harbor run --path tasks/thanos/amr-mhd-restart --agent nop --env docker --jobs-dir /tmp/terminal-portfolio-nop
```

Oracle is expected to earn reward 1; NOP is expected to earn reward 0. Use the task's own container and verifier rather than executing its repair script against the host filesystem.

## Scope of the stamps

The task files retain their original content, including existing authorship disclosures and local task identifiers. The portfolio packaging check verified source-byte matches, entry points, TOML parsing, Python/shell syntax and local Docker COPY inputs. Containers and model trials were not rerun for publication.

Recorded Pluto and Dynamo figures are labeled separately from reviewed raw results. A case replay is not a fresh solver trial. Runtime failures, provider errors, timeouts and numerical boundary rejections are not automatically counted as analytical stumps. The current TB4 v6 package remains explicitly uncalibrated; historical v5 scores do not describe it.
