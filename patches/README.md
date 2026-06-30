# V8 Patch Profiles

For detailed instructions on adapting V8 library patches across versions and
platforms, read:

```text
patches/v8/PATCH_GUIDE.md
```

The maintainer/agent V8 build flow applies patches in this order:

```text
Disassembler/v8.patch
patches/v8/common/*.patch
patches/v8/platform/<target-platform>/*.patch
patches/v8/<v8-version>/*.patch
patches/v8/<v8-version>/<target-platform>/*.patch
--patch-file <extra.patch>
```

Target platform examples:

```text
mac-x64
mac-arm64
win-x64
linux-x64
linux-arm64
```

Use this layout when a V8 branch or target needs a different patch:

```text
patches/v8/
  common/
    001-print-bytecode.patch
  platform/
    win-x64/
      010-windows-build-fix.patch
  8.5.210.26/
    001-serializer-layout.patch
    mac-x64/
      020-mac-x64-fix.patch
    win-x64/
      020-win-x64-fix.patch
```

If the default `Disassembler/v8.patch` is wrong for a version, run with:

```bash
python3 v8_builder.py \
  --v8-version <version> \
  --build-v8dasm \
  --install-dir Bin \
  --no-default-patches \
  --patch-file /path/to/version-specific.patch
```

Patch files are applied with `git apply`. Already-applied patches are detected
with `git apply --reverse --check` and skipped.
