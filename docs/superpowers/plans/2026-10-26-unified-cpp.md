# Unified C++ traffic implementation plan

Goal: one constructed-road driver with the union of supported features, on cpp.
Architecture: staged C++ decisions and movement behind the existing Python world/UI boundary; frozen Python references only in tests.
Spec: ../specs/2026-10-26-unified-cpp-design.md

- [x] Freeze independent Python references and record date/feature precedence.
- [x] Make cpp the only production mode; route spawning, admission and stepping directly into C++; migrate launchers, construction and tools.
- [x] Adapt differential tests to the frozen references, preserving behavior assertions; add checks for a sole C++ driver and explicit failure on old modes.
- [x] Compare staged Python and C++ features and port missing newer behavior; test signals, edits, deadlock, merges and admission.
- [x] Run targeted and complete regressions; resolve substantive failures, benchmark the consolidated driver, review, and publish cpp with an expected-SHA check.
