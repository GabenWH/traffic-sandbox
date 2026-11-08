# Shared vehicle state in production

User direction: fully implement and push shared mode, with no further copy-mode development.

The application will always attach live native vehicle and brain views. Keep the
`native_output_mode` keyword accepting only `shared` so callers requesting retired
copy mode receive a clear migration error. Remove eager per-tick synchronization
and copy/shared benchmark comparisons. Explicit owned diagnostic snapshots remain.

Preserve vehicle identity, public edits, source/RNG synchronization, road rebuilds,
completion events, stationary loading bodies, save/load and renderer reads. Native
storage must outlive attached views; detach to ordinary objects before releasing
it. Leave driving algorithms unchanged and engine.cpp below 2,000 readable lines.

Approaches considered: retain dual runtime modes (rejected by user direction),
or promote shared views as the sole runtime path (selected). Implement in Python
using the existing ctypes ABI, with regression coverage and shared-only tools.

Additional user request: fix the live test viewer sliding left during zoom. Keep
the map location under the cursor fixed after pan and zoom; preserve zoom limits.
Include the visual Arcata launcher so the corrected viewer is reproducible.
