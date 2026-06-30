# V8 Bytecode Decompiler CUI

This workspace is organized as a small command-line decompiler framework for
V8/bytenode cached bytecode.

This fork is inspired by and built on
[`j4k0xb/View8`](https://github.com/j4k0xb/View8). The V8 version hash detector
was ported to Python from
[`j4k0xb/v8-version-analyzer`](https://github.com/j4k0xb/v8-version-analyzer).

## Main Entry Point

```bash
python3 decompiler.py --help
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run tests:

```bash
python -m unittest tests/test_view8.py
```

## Common Commands

Detect the V8 version hash:

```bash
python3 decompiler.py detect /path/to/file.jsc
```

Run the full pipeline:

```bash
python3 decompiler.py all /path/to/file.jsc -o /tmp/decompiled-file --check
```

This writes:

- `<name>.version.json`
- `<name>.snir.json`
- `<name>.pseudo.js`
- `<name>.constants.js`

Export only SNIR:

```bash
python3 decompiler.py lift /path/to/file.jsc /tmp/file.snir.json -f snir
```

Recover constants from an existing SNIR file:

```bash
python3 decompiler.py recover /tmp/file.snir.json /tmp/file.constants.js --check
```

Batch process a directory:

```bash
python3 decompiler.py batch /path/to/extracted-app/app/js -o /tmp/decompiled --glob '*.jsc' --keep-going
```

`decompiler.py` intentionally does not build V8. Patched `v8dasm` build
guidance for maintainers and coding agents is kept in:

```text
AGENTS.md
patches/v8/PATCH_GUIDE.md
```

## Repository Layout

- `Parser/`, `Translate/`, `Simplify/`, `Disassembler/`: View8-compatible core modules.
- `IR/`: SNIR schema and V8 bytecode lifter.
- `Bin/`: bundled `v8dasm` helper binaries.
- `tools/recover_from_snir.py`: constant-pool based source reconstruction.
- `v8_builder.py`: maintainer/agent helper for preparing additional `v8dasm` binaries.

## Technical Specification

Implementation contracts and SNIR details are documented in:

```text
docs/TECHNICAL_SPEC.md
```

## Bundled Binaries

The repository currently includes one ready-to-use helper:

```text
Bin/8.5.210.26-mac-x64-v8dasm
```

Additional versions/platforms should be prepared by maintainers or coding
agents using `AGENTS.md`. Generated V8 source trees and build caches are
ignored by git.

## Notes

Cached bytecode does not preserve exact original JavaScript source. The CUI
therefore produces multiple projections:

- SNIR JSON for structured analysis.
- pseudo JS from View8's decompiler.
- recovered constants/CommonJS modules from surviving constant pools.
