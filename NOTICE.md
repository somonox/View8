# Notices

This repository is a fork inspired by and built on j4k0xb's tooling around V8
cached bytecode analysis.

- The repository root is based on `j4k0xb/View8`
  (https://github.com/j4k0xb/View8) and includes local parser/lifter/CUI
  changes.
- The V8 version hash detector in `Parser/v8_version.py` was ported to Python
  from `j4k0xb/v8-version-analyzer`
  (https://github.com/j4k0xb/v8-version-analyzer).
- `Disassembler/v8dasm.cpp` and V8 source patches are used to build a
  patched `v8dasm` helper for cached bytecode inspection.

Generated analysis outputs, extracted applications, and V8 build trees are not
intended to be committed.
