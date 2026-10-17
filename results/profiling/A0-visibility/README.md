# Observability checkpoint 3: viewer integration

All checkpoint gates passed. Compiler kernel optimization has not started.

Schema-v2 exports now support the measured compiler A0 and regenerated LiteRT B0.
Execution scopes are independent of logical nodes. Split units aggregate once;
fused/shared costs retain their full measurement; eliminated nodes are unavailable.
A0 has no allocation event. Source/assembly/CFG/register exploration and verified
GCC analysis remain available. The compiler inspector exposes implementation,
backend, prepared integers, source regions and supporting artifacts. Planned memory
shows offsets, inclusive execution-step lifetimes, aliases, scratch and peak storage.

The A0 export consumes the immutable repeated capture and GCC archive. It uses
frozen sources, rechecks binary/dependency links and excludes weight/ELF payloads.
Tests explicitly deny access to live compiled-source files. Import validates archive
integrity, resource limits, exact uint64 counters, scope boundaries and per-PC
conservation. Real A0/B0 and synthetic shared/split/eliminated views pass browser
acceptance. A screenshot is saved in `build/compiler/checkpoint-3-A0-viewer.png`.

Validation: **153 compiler**, **5 collector**, **20 export/static**, **66 frontend**
and **11 browser** tests passed, plus the production viewer build, Ruff and diff checks.
All 40 frozen B0 files and the production A0 ELF remain unchanged. Ordinary Spike
again matches all 1,000 public output bytes; native/capture/sanitized gates retain
all complete oracle comparisons and the explicit zero-point Softmax diagnostic.

No new full profile was collected: target behavior is unchanged. The verified A0
capture remains **6,063,975,187 instructions**, including **85** invocation-overhead
instructions, versus **4,867,278,370** for B0 (**+24.58657%**). Isolated replay remains
separate evidence. This checkpoint makes no optimization or hardware-speed claim.

```sh
gmake compiler-export
gmake explorer-dev PROFILE_CONFIGURATION=A0
# Complete visibility acceptance (requires saved A0 capture and GCC evidence):
gmake compiler-visibility-checkpoint
```

Open **Explore A0 build**, or import `build/explorer/A0.zip`. B0 is regenerated
with `gmake explorer-export`. To omit optional GCC dumps: `gmake compiler-export
COMPILER_ANALYSIS=`. Schema v1 is intentionally unsupported. Checkpoint comparison,
live simulator integration and browser job launching remain outside viewer scope.

See [workflow](../../../docs/compiler-profiling.md) and [viewer documentation](../../../docs/explorer.md).
Bundle identities, sizes, executable hashes, coverage and test-log hashes are in
[summary.json](summary.json). Generated bundles/captures remain in ignored build storage.
