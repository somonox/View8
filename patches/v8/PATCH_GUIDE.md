# V8 Library Patch Guide

This guide is for humans and AI agents adapting the V8 source patches needed
to build `v8dasm` for a new V8 version or platform.

The goal is not to fork V8 permanently. The goal is to apply the smallest patch
set that makes V8 print enough information from cached bytecode for View8 to
parse it.

## Patch Goals

The patched V8 library must:

1. Accept cached bytecode even when the source hash or magic checks would
   normally reject it.
2. Print `SharedFunctionInfo` records after deserialization.
3. Print each active `BytecodeArray` between stable markers.
4. Print nested constant-pool objects deeply enough for reconstruction:
   `FixedArray`, object boilerplates, double arrays, shared functions, and
   array boilerplates.
5. Avoid truncating long strings in debug output.

The output format must keep these markers stable because View8 parses them:

```text
Start SharedFunctionInfo
...
Start BytecodeArray
...
End BytecodeArray
...
End SharedFunctionInfo

Start FixedArray
...
End FixedArray
```

## Current Baseline Patch

The default patch is:

```text
Disassembler/v8.patch
```

It was written against V8 8.5-era sources. Treat it as a semantic reference, not
as a universal patch.

When it fails on another V8 version, recreate the same behavior in the new
source layout instead of forcing offsets.

## Source Areas To Inspect

The file names move between V8 versions. Start with these search terms:

```bash
rg -n "SharedFunctionInfoPrint|BytecodeArray.*Disassemble|PrintSourceCode" src
rg -n "HeapObjectShortPrint|FixedArrayPrint|ObjectBoilerplateDescriptionPrint" src
rg -n "StringShortPrint|kMaxShortPrintLength|PrintUC16" src
rg -n "CodeSerializer::Deserialize|SerializedCodeData::SanityCheck|SanityCheckJustSource" src
rg -n "magic_number_|SerializedData::kMagicNumber|Deserializer<" src
```

Likely files by V8 generation:

```text
src/diagnostics/objects-printer.cc
src/objects/objects.cc
src/objects/string.cc
src/snapshot/code-serializer.cc
src/snapshot/deserializer.cc
```

On newer or older versions, equivalent code may be under:

```text
src/objects/objects-printer.cc
src/objects/string-inl.h
src/snapshot/code-serializer.cc
src/snapshot/deserializer.cc
src/snapshot/snapshot-source-sink.cc
```

## Required Semantic Changes

### 1. SharedFunctionInfo Printing

Find the method that prints `SharedFunctionInfo`.

Required behavior:

```cpp
os << "\nStart BytecodeArray\n";
this->GetActiveBytecodeArray().Disassemble(os);
os << "\nEnd BytecodeArray\n";
os << std::flush;
```

The exact accessor may differ:

```cpp
GetActiveBytecodeArray()
GetBytecodeArray(isolate)
bytecode_array()
function_data(...)
```

Use the accessor that is valid for the target V8 version. If bytecode can be
lazy or missing, guard the call and still emit a stable section when possible.

### 2. Deserialization Print Hook

Find `CodeSerializer::Deserialize` or the nearest cached-code deserialization
success path.

Required behavior after successful `SharedFunctionInfo` recovery:

```cpp
std::cout << "\nStart SharedFunctionInfo\n";
result->SharedFunctionInfoPrint(std::cout);
std::cout << "\nEnd SharedFunctionInfo\n";
std::cout << std::flush;
```

If `result` is a handle, use the version-correct syntax:

```cpp
result->SharedFunctionInfoPrint(std::cout);
(*result).SharedFunctionInfoPrint(std::cout);
SharedFunctionInfo::cast(*result).SharedFunctionInfoPrint(std::cout);
```

### 3. Cache Sanity Checks

Find cached-code sanity checks.

The baseline behavior is intentionally permissive:

```cpp
return SerializedCodeSanityCheckResult::kSuccess;
```

or the equivalent success enum for that V8 version.

This is needed because bytenode/electron cachedData often has a different
source hash than the dummy source fed to `v8dasm`.

### 4. Magic Number Check

Some V8 versions reject cached data early with:

```cpp
CHECK_EQ(magic_number_, SerializedData::kMagicNumber);
```

The baseline patch removes this assertion. On versions where the check moved,
disable the equivalent hard abort and prefer returning a recoverable failure
only if continuing is impossible.

### 5. Deep Constant Pool Printing

Find `HeapObjectShortPrint` or equivalent object short printer.

Required behavior:

```cpp
case FIXED_ARRAY_TYPE:
  os << "<FixedArray[" << FixedArray::cast(*this).length() << "]>";
  os << "\nStart FixedArray\n";
  FixedArray::cast(*this).FixedArrayPrint(os);
  os << "\nEnd FixedArray\n";
  break;
```

Also support, when present:

```cpp
OBJECT_BOILERPLATE_DESCRIPTION_TYPE
FIXED_DOUBLE_ARRAY_TYPE
SHARED_FUNCTION_INFO_TYPE
ASM_WASM_DATA_TYPE / ArrayBoilerplateDescription
```

The important property is that nested constants print recursively with stable
markers. View8 can tolerate extra text better than missing object contents.

### 6. Long String Printing

Find the short string printer and remove or bypass truncation like:

```cpp
if (len > kMaxShortPrintLength) {
  ... "...<truncated>>" ...
  return;
}
```

View8 needs full string constants. This matters for large object literals,
embedded HTML, base64 data, and settings registries.

## Platform-Specific Notes

Patch source semantics should usually be platform-independent.

Platform-specific files should only handle build differences:

```text
patches/v8/platform/win-x64/*.patch
patches/v8/platform/mac-x64/*.patch
patches/v8/platform/mac-arm64/*.patch
patches/v8/platform/linux-x64/*.patch
patches/v8/platform/linux-arm64/*.patch
```

Examples of platform-specific concerns:

```text
Windows:
- MSVC warning fixes
- missing include guards
- library link differences

mac-arm64 building mac-x64:
- CIPD platform override
- target_cpu="x64"
- -arch x86_64 for custom v8dasm link

Linux:
- -ldl / -lrt link behavior
```

Do not put V8 semantic output changes in platform directories unless the source
layout truly differs by platform.

## Version-Specific Layout

Use this layout for patch profiles:

```text
patches/v8/
  common/
    001-shared-output.patch
  platform/
    win-x64/
      001-msvc-link.patch
  8.5.210.26/
    001-v8-8.5-output.patch
    win-x64/
      002-v8-8.5-win-fix.patch
```

Apply order is:

```text
Disassembler/v8.patch
patches/v8/common/*.patch
patches/v8/platform/<target-platform>/*.patch
patches/v8/<v8-version>/*.patch
patches/v8/<v8-version>/<target-platform>/*.patch
--patch-file <extra.patch>
```

If the baseline patch does not apply, use:

```bash
python3 v8_builder.py \
  --v8-version <version> \
  --build-v8dasm \
  --install-dir Bin \
  --no-default-patches \
  --patch-file patches/v8/<version>/001-output.patch
```

## Validation Checklist

After building `v8dasm`, validate on a known `.jsc`:

```bash
python3 decompiler.py lift sample.jsc /tmp/sample.snir.json -f snir \
  --v8 <version> \
  --v8dasm Bin/<version>-<platform>-v8dasm
```

Then check:

```bash
python3 - <<'PY'
import json
d=json.load(open('/tmp/sample.snir.json'))
print('functions', len(d.get('functions', [])))
print('const pools', sum(len(f.get('constant_pool', [])) for f in d.get('functions', [])))
PY
```

A good patch usually produces:

```text
functions > 0
constant pools > 0
```

For settings-heavy modules, object constants should survive as readable object
literal strings rather than truncated strings.

## Failure Triage

Patch does not apply:

```text
Find the semantic target by search term, rewrite patch for this V8 layout.
Do not force fuzzy offsets if the surrounding API changed.
```

Build fails after patch:

```text
Check whether the accessor names changed:
- GetActiveBytecodeArray
- Disassemble
- SharedFunctionInfoPrint
- cast syntax
```

SNIR has functions but no constants:

```text
Deep constant-pool printing is incomplete. Revisit HeapObjectShortPrint and
object/array boilerplate printers.
```

Strings are cut:

```text
StringShortPrint truncation still exists somewhere.
```

CachedData rejected:

```text
SanityCheck or magic-number rejection still triggers before printing.
```

Process crashes:

```text
A bytecode accessor is being called on a function without bytecode. Add guards
for missing bytecode while keeping output markers stable.
```

## What Not To Do

Do not:

- Add broad refactors to V8.
- Change output marker names casually.
- Mix source semantic patches with platform linker patches.
- Treat Base64/large HTML strings as noise; they are often useful constants.
- Assume a patch for one V8 major version is valid for another.
