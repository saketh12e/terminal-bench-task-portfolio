# Acceptance invariants

All 85 checks must pass. These are behavioral requirements, not instructions to reproduce a particular source layout. Each ID below has a separate reported result. Repeated conserved-component checks matter independently: repairing mass or momentum does not repair total energy or Bz.

The adaptive-time and authoritative canonical-checkpoint specification in /app/data/adaptive-time.md is included. The same 85 families also cover unequal nested substeps, nonuniform coarse durations, changed future schedules, repeated fresh-process continuation and independently corrected supplied receipts. These are semantic extensions of recovery; no minimum tool-call count is graded. All existing tolerances below are retained.

Unless a narrower bound is stated, numerical equality means NumPy-style `abs(actual-expected) <= 2e-10 + 2e-10*abs(expected)` in float64. This accommodates ordinary arithmetic ordering; bitwise identity is not required. Discrete divergence has absolute limit 3e-9 in field/length units on the unit domain. Periodic endpoint faces agree within `1e-12 + 1e-12*abs(expected)`. Density and diagnostic gas pressure must exceed 1e-8. Source and artifact files must be regular local files. An invocation produces at most 128 MiB of HDF5 and 4 MiB of JSON; individual float64 datasets contain at most 2,000,000 elements. No external/soft HDF5 links, external storage or virtual datasets are allowed.

Wave error is the volume-weighted mean absolute error over selected cell components, counting fine leaves and uncovered coarse cells once, divided by the component count. Alfvén accuracy selects (mx,my,mz,Bz); entropy selects (rho,mx,my,E). The reference is the continuum cell average at the physical time, using the numerical-initialization convention described in /app/data/numerics.md. Smooth adaptive convergence compares base n=16,32,64 at the same time with scaled patch locations, synchronized patch motion and ownership migration: both successive error ratios must exceed 2.15. The n=64 Alfvén error must be below 2e-4. At n=48, evolved x, y and oblique waves must each have error below 2.8e-4 and a Bz change exceeding .01 for the nondegenerate propagation probes. Their maximum density and pressure deviations from the analytic constants are below .005 and .006 respectively. Entropy error at n=32 is below .0015.

I73 also checks time-refinement stability independently of spatial error. On n=24 with patch [6,18,6,18], evolve the Alfvén case (wavevector [1,1], amplitude .07, phase .417, density 1.2, pressure .9, field .83, velocity .21) to time .06 with coarse dt=.06/24 and dt=.06/96, without events. The volume-weighted mean absolute difference over all six conserved components must be below 5e-6. A half-step resolution is also exercised. This bound permits alternative accurate time integrators and ordinary spatial truncation error; it detects using the final coarse boundary state for all fine stages even when global conservation and divergence look correct.

Loop and pressure probes use n=32, amplitude .12 and elapsed time .075. Their six-component leaf L1 error, component by component, against a uniform n=64 ideal-MHD solution from the supplied working kernel is below 2e-4. The uniform solution uses steps no greater than .025/64. Loop momentum change exceeds 8e-5 and Bx change exceeds .001; pressure-pulse momentum change exceeds .003. These are dynamic MHD tests, with conservation and positivity also required. For three-level dynamic probes, the same six-component 2e-4 envelope is measured against a uniform n=128 reference with steps no greater than .025/128; that reference resolves the finest spacing. The additional analytic wave and convergence checks are independent of that trusted uniform kernel.

All adjacent-pair rules apply at BOTH interfaces when nested refinement is active. I01-I15 and I18-I35 cover all three levels; I36-I59 additionally check the nested predictor, both inner substeps, inner synchronization and effective exported receipt identities. I60-I65 include interruptions in both root halves at each inner phase, with distinct nonzero ancestor/descendant registers. I66-I68 cover migrations of each active level while both transactions are pending. I69-I72 cover inner replacement, outer motion with global-coordinate inner overlap, removal and reappearance. I82-I85 bind nested metadata, actual per-level clocks, exactly-once event consumption and full nested artifact reproduction to the requested configuration. These expand the same 85 invariant families, not a tool-use quota.

The verifier exercises the public campaign plus held-out values and combinations inside /app/data/contract.md. It reruns submitted source in fresh processes, pauses at every declared phase, continues checkpoints, regrids, and permutes logical owners. It recomputes balances and audit diagnostics from arrays. No numerical requirement is inferred from an audit pass flag. The invariant descriptions below use the field, face, phase and integral definitions in /app/data/numerics.md.

| ID | Invariant | Acceptance rule |
|---|---|---|
| I01 | mass balance | Synchronized periodic leaf integral of density equals its discrete initial integral, including regrids and migration. |
| I02 | momentum x balance | Synchronized periodic leaf integral of x momentum equals its discrete initial integral, including regrids and migration. |
| I03 | momentum y balance | Synchronized periodic leaf integral of y momentum equals its discrete initial integral, including regrids and migration. |
| I04 | momentum z balance | Synchronized periodic leaf integral of z momentum equals its discrete initial integral, including regrids and migration. |
| I05 | total energy balance | Synchronized periodic leaf integral of total energy equals its discrete initial integral, including regrids and migration. |
| I06 | magnetic z balance | Synchronized periodic leaf integral of Bz equals its discrete initial integral, including regrids and migration. |
| I07 | mean magnetic x | Periodic x-cut magnetic flux equals its initial value. |
| I08 | mean magnetic y | Periodic y-cut magnetic flux equals its initial value. |
| I09 | coarse solenoidality | Every coarse cell has staggered divergence within 3e-9. |
| I10 | fine solenoidality | Every active refined cell has staggered divergence within 3e-9. |
| I11 | positive density | All active levels have density above 1e-8. |
| I12 | positive pressure | All active levels have diagnostic gas pressure above 1e-8. |
| I13 | finite conserved fields | Every conserved field value is finite float64. |
| I14 | finite x faces | Every x-face field value is finite float64. |
| I15 | finite y faces | Every y-face field value is finite float64. |
| I16 | periodic x seam | Duplicate periodic x-normal endpoint faces agree at seam tolerance. |
| I17 | periodic y seam | Duplicate periodic y-normal endpoint faces agree at seam tolerance. |
| I18 | density restriction | Covered coarse density equals the mean of its four fine children. |
| I19 | momentum x restriction | Covered coarse x momentum equals the mean of its four fine children. |
| I20 | momentum y restriction | Covered coarse y momentum equals the mean of its four fine children. |
| I21 | momentum z restriction | Covered coarse z momentum equals the mean of its four fine children. |
| I22 | energy restriction | Covered coarse total energy equals the mean of its four fine children. |
| I23 | bz restriction | Covered coarse Bz equals the mean of its four fine children. |
| I24 | x face area restriction | Covered and interface coarse Bx equals the area mean of its two coincident fine faces. |
| I25 | y face area restriction | Covered and interface coarse By equals the area mean of its two coincident fine faces. |
| I26 | density prolongation | Initial fine-child means preserve coarse density; saved initial coarse density matches the declared initial condition. |
| I27 | momentum x prolongation | Initial fine-child means preserve coarse x momentum; saved initial coarse x momentum matches the declared initial condition. |
| I28 | momentum y prolongation | Initial fine-child means preserve coarse y momentum; saved initial coarse y momentum matches the declared initial condition. |
| I29 | momentum z prolongation | Initial fine-child means preserve coarse z momentum; saved initial coarse z momentum matches the declared initial condition. |
| I30 | energy prolongation | Initial fine-child means preserve coarse total energy; saved initial coarse total energy matches the declared initial condition. |
| I31 | bz prolongation | Initial fine-child means preserve coarse Bz; saved initial coarse Bz matches the declared initial condition. |
| I32 | x face prolongation | Initial refined Bx preserves coarse normal-face means; saved initial coarse Bx matches initialization. |
| I33 | y face prolongation | Initial refined By preserves coarse normal-face means; saved initial coarse By matches initialization. |
| I34 | prolongation coarse divergence | The initial coarse magnetic field is discretely solenoidal. |
| I35 | prolongation child divergence | Every child of the initial solenoidal refinement is solenoidal. |
| I36 | coarse mass flux | Provisional coarse density is reproduced by the saved coarse integrated face-flux divergence. |
| I37 | coarse momentum x flux | Provisional coarse x momentum is reproduced by the saved coarse integrated face-flux divergence. |
| I38 | coarse momentum y flux | Provisional coarse y momentum is reproduced by the saved coarse integrated face-flux divergence. |
| I39 | coarse momentum z flux | Provisional coarse z momentum is reproduced by the saved coarse integrated face-flux divergence. |
| I40 | coarse energy flux | Provisional coarse total energy is reproduced by the saved coarse integrated face-flux divergence. |
| I41 | coarse bz flux | Provisional coarse Bz is reproduced by the saved coarse integrated face-flux divergence. |
| I42 | coarse faraday x | Saved coarse electric integrals reproduce the provisional Bx Faraday update. |
| I43 | coarse faraday y | Saved coarse electric integrals reproduce the provisional By Faraday update. |
| I44 | fine mass integrals | Fine density after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I45 | fine momentum x integrals | Fine x momentum after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I46 | fine momentum y integrals | Fine y momentum after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I47 | fine momentum z integrals | Fine z momentum after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I48 | fine energy integrals | Fine total energy after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I49 | fine bz integrals | Fine Bz after two substeps is reproduced by the sum of both substeps' integrated face-flux divergences. |
| I50 | fine faraday x | Accumulated fine electric integrals reproduce the Bx change through both substeps. |
| I51 | fine faraday y | Accumulated fine electric integrals reproduce the By change through both substeps. |
| I52 | mass reflux | Synchronized coarse density is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I53 | momentum x reflux | Synchronized coarse x momentum is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I54 | momentum y reflux | Synchronized coarse y momentum is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I55 | momentum z reflux | Synchronized coarse z momentum is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I56 | energy reflux | Synchronized coarse total energy is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I57 | bz reflux | Synchronized coarse Bz is reproduced by signed fine-minus-coarse interface flux accounting and covered-cell restriction. |
| I58 | reflux curl x | The perimeter electric mismatch curl and face restriction reproduce synchronized coarse Bx, including neighboring uncovered faces. |
| I59 | reflux curl y | The perimeter electric mismatch curl and face restriction reproduce synchronized coarse By, including neighboring uncovered faces. |
| I60 | synchronized restart | Fresh-process synchronized restart reproduces uninterrupted final U/B and topology. |
| I61 | predicted restart | Fresh-process restart after the coarse prediction reproduces uninterrupted final U/B and topology. |
| I62 | first fine step restart | Fresh-process restart after fine substep one reproduces uninterrupted final U/B and topology. |
| I63 | completed fine step restart | Fresh-process restart before synchronization, with both fine steps complete, reproduces uninterrupted final U/B and topology. |
| I64 | restart initial balance | All four restart continuations preserve each initial conserved leaf integral. |
| I65 | restart register consumption | After synchronization, old/pending integral groups are absent or inert zero arrays. |
| I66 | migrated flux registers | Ownership permutation preserves every unconsumed coarse/fine face-flux integral. |
| I67 | migrated electric registers | Ownership permutation preserves every unconsumed coarse/fine electric integral. |
| I68 | migrated time bracket | Ownership permutation preserves the old coarse time-bracket fields. |
| I69 | regrid leaf balance | Synchronized patch replacement preserves all six leaf integrals. |
| I70 | regrid solenoidality | Patch replacement preserves coarse and fine solenoidality. |
| I71 | regrid cell overlap | Retained old/new patch overlap preserves every fine conserved cell value. |
| I72 | regrid face overlap | Retained overlap preserves all valid fine normal-face fields. |
| I73 | adaptive wave accuracy | The evolving adaptive n=64 Alfvén wave meets the stated absolute error envelope, and the fixed-mesh time-refinement probe differs by less than 5e-6. |
| I74 | x alfven propagation | The x-directed Alfvén wave propagates and meets the stated analytic error envelope. |
| I75 | y alfven propagation | The y-directed Alfvén wave propagates and meets the stated analytic error envelope. |
| I76 | oblique alfven propagation | The oblique Alfvén wave propagates and meets the stated analytic error envelope. |
| I77 | adaptive convergence | Both adaptive refinement error ratios exceed 2.15 under moving-patch evolution. |
| I78 | wave thermodynamics | Alfvén density and pressure stay within the stated thermodynamic truncation-error bounds. |
| I79 | entropy transport | The entropy contact follows the analytic translated cell-average profile. |
| I80 | loop lorentz response | The magnetic loop has genuine Lorentz response, conserved leaf quantities and agreement with the uniform dynamic reference. |
| I81 | pressure response | The pressure perturbation has genuine momentum response, positive pressure, conserved leaf quantities and agreement with the uniform dynamic reference. |
| I82 | audit field agreement | Audit totals, initial totals, minima, divergence, metadata and clocks match independent measurements of the HDF5 arrays. |
| I83 | checkpoint clocks and cursor | Stopped checkpoint level clocks, owner and processed-event cursor match the declared phase, including same-phase migration. |
| I84 | artifact source reproduction | The delivered recovery and audit for the required campaign reproduce fresh execution of the submitted source. |
| I85 | campaign identity and completion | The canonical campaign hash, final synchronized time, completion flag and processed-event count agree with the requested campaign. |
