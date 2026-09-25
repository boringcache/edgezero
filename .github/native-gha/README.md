# EdgeZero native compiler storage rolling comparison

The manual workflow compares sccache's native GitHub Actions backend with
BoringCache compiler storage. Each provider builds one cold seed four first-parent
commits before the pinned application endpoint, then builds each of the next four
revisions once. `source-window.json` records the five exact revisions in order.

Each revision runs on a fresh runner with an empty target directory. Both backends
retain the same cache namespace across the sequence and publish newly compiled
results after each build. Explicit job dependencies preserve revision order. Jobs
run sequentially to avoid adding concurrent benchmark clients to GitHub's cache
request load. There are no repeated cold samples or same-source warm reruns.

Both providers use the same application revision at each step, deployment action
revision, Ubuntu runner class, Rust container digest, sccache version, and CLI
producer command. Neither provider restores Cargo targets, dependencies, or a
local sccache directory. The build container receives the native backend
configuration; the GitHub runtime credential is passed through the process
environment and is not printed or saved in evidence. Only manually dispatched
builds of pinned sources run this workflow.

The build timer includes the unchanged CLI producer command, native statistics
collection, and sccache shutdown. Runner setup, container preparation, BoringCache
setup, and Action post-job work are outside that timer and remain visible as job
steps. Retained artifacts include source identities, build timing, compiler
statistics, output validation, and BoringCache's emitted evidence.

Report cache errors with timings. A successful build can fall back to compilation
when native GitHub cache storage fails. A changed-source build with an unusable
seed is not a healthy rolling-cache comparison. Three of the four changes affect
code or dependencies; the first changes documentation. This sequence measures
compiler-cache reuse across revisions, not cross-repository access.

Each complete workflow attempt gets a new cache namespace. Start the complete
workflow again if the seed fails; rerunning only later jobs would use a new
namespace without the earlier seed.

The earlier directory-cache comparison and rolling workflow remain available in
commit `0ba564a23b1f61c1450c21e37cdd62ae0c0de9bf`. Its timings must not be labelled
as native GitHub Actions backend results.
