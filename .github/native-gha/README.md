# EdgeZero native compiler storage comparison

The manual `BoringCache native GHA comparison` workflow compares sccache's native
GitHub Actions backend with BoringCache compiler storage. It runs three independent
cold seeds per provider, then three matching read-only warm builds on fresh runners.
Jobs run sequentially to avoid adding concurrent benchmark clients to GitHub's cache
request load. Each pair has a separate cache namespace for the workflow attempt.

Both providers use the same application revision, deployment action revision,
Ubuntu runner class, Rust container digest, sccache version, and CLI producer command.
Neither provider restores Cargo targets, dependencies, or a local sccache directory.
The build container receives the native backend configuration; the GitHub runtime
credential is passed through the process environment and is not printed or saved
in evidence. Only manually dispatched builds of pinned sources run this workflow.

The build timer includes the unchanged CLI producer command, native statistics
collection, and sccache shutdown. Runner setup, container preparation, BoringCache
setup, and Action post-job work are outside that timer and remain visible as job
steps. Retained artifacts include source identities, build timing, compiler
statistics, output validation, and BoringCache's emitted evidence.

Report cache errors with timings. A successful build can fall back to compilation
when native GitHub cache storage fails; that is not a healthy warm-cache comparison.
These same-source pairs do not measure changed-source or cross-repository reuse.

The earlier directory-cache comparison and rolling workflow remain available in
commit `0ba564a23b1f61c1450c21e37cdd62ae0c0de9bf`. Its timings must not be labelled
as native GitHub Actions backend results.
