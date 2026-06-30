# Agent Guide

This repository is a CUI decompiler framework. Keep the public command surface
focused on bytecode analysis:

```text
detect
lift
recover
all
batch
```

Do not add a `build-v8dasm` subcommand to `decompiler.py`. Building patched V8
is an environment-heavy maintainer task, not a normal decompiler operation.

## Patched v8dasm Builds

Use `v8_builder.py` directly when a new V8 helper binary is needed:

```bash
python3 v8_builder.py \
  --v8-version <version> \
  --build-v8dasm \
  --target-platform auto \
  --install-dir Bin
```

The installed binary name must follow this convention:

```text
Bin/<v8-version>-<platform>-v8dasm[.exe]
```

Examples:

```text
Bin/8.5.210.26-mac-x64-v8dasm
Bin/8.5.210.26-mac-arm64-v8dasm
Bin/8.5.210.26-win-x64-v8dasm.exe
```

Supported target labels are:

```text
auto
mac-x64
mac-arm64
win-x64
linux-x64
linux-arm64
```

Prefer building on the matching host platform. Windows targets should be built
on Windows, macOS targets on macOS, and Linux targets on Linux. Use
`--allow-cross` only when the Chromium/V8 toolchain for that target is already
configured and verified locally. Apple Silicon macOS may build `mac-x64` with
the builder's CIPD platform override.

## Patch Policy

Read `patches/v8/PATCH_GUIDE.md` before changing V8 patches. Patch selection is
version/platform aware and should stay narrow:

```text
Disassembler/v8.patch
patches/v8/common/*.patch
patches/v8/platform/<target-platform>/*.patch
patches/v8/<v8-version>/*.patch
patches/v8/<v8-version>/<target-platform>/*.patch
--patch-file <extra.patch>
```

If the baseline patch is wrong for a V8 branch, keep the replacement under
`patches/v8/<version>/` or `patches/v8/<version>/<platform>/` and run:

```bash
python3 v8_builder.py \
  --v8-version <version> \
  --build-v8dasm \
  --install-dir Bin \
  --no-default-patches \
  --patch-file patches/v8/<version>/001-output.patch
```

## Validation

After installing a new helper binary, validate it with a known `.jsc`:

```bash
python3 decompiler.py lift sample.jsc /tmp/sample.snir.json -f snir \
  --v8 <version> \
  --v8dasm Bin/<version>-<platform>-v8dasm
```

Then run the repository checks:

```bash
python3 -m unittest tests/test_view8.py
python3 -m py_compile decompiler.py v8_builder.py tools/recover_from_snir.py
```

Do not commit V8 source trees, build caches, extracted application contents,
generated SNIR, recovered JavaScript, `.venv`, or Python cache directories.
