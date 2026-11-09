# Solver checkout

The uniform-grid finite-volume kernel and case initializer are supplied working components. The recovery integration branch is the current operational snapshot. The command-line interface, array layout and acceptance contract are under /app/data.

The code separates staggered mesh transfer, subcycle boundary construction, interface accumulation, hierarchy ownership, regridding and checkpoint serialization. The runner accepts any published campaign and emits fields with diagnostic metadata. A successful run is not evidence that the physical balances or restart equivalence are correct.

The operational snapshot predates the adaptive clock and portable restart contract in /app/data/adaptive-time.md. Its nominal-step arithmetic, atomic inner service, and cache assumptions require integration repairs. Preserve the working uniform-grid physics while implementing the full published recovery interface.
