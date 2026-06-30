# Technical Specification

## 1. Scope

This project is a command-line decompiler framework for V8/bytenode cached
bytecode. It wraps View8, V8 version detection, SNIR lifting, and conservative
source-like recovery into one CUI-oriented workflow.

The project has two explicit boundaries:

- `decompiler.py` is the user-facing analysis CUI.
- patched V8 and `v8dasm` builds are maintainer/agent tasks documented in
  `AGENTS.md` and `patches/v8/PATCH_GUIDE.md`.

`decompiler.py` must not expose a `build-v8dasm` command. This keeps normal
analysis deterministic and avoids mixing heavyweight platform-specific V8 build
state with decompilation.

## 2. Goals

- Detect the V8 version hash embedded in cached bytecode.
- Select or accept a compatible `v8dasm` helper binary.
- Export View8 formats, including SNIR JSON.
- Preserve V8 bytecode information as semantic atoms, provenance facts,
  dependence edges, equivalence candidates, and high-level hypotheses.
- Recover source-like JavaScript fragments from surviving constant-pool data.
- Provide tests and schema checks for the current SNIR contract.

## 3. Non-Goals

- Exact original JavaScript source recovery.
- Full JavaScript type reconstruction.
- Full control-flow structuring into exact `if`, `while`, `switch`, or
  exception syntax.
- Building patched V8 from the public CUI.
- Guaranteeing cross-platform `v8dasm` binaries without matching host/toolchain
  validation.

## 4. Repository Layout

```text
.
├── view8.py
├── decompiler.py
├── v8_builder.py
├── Bin/
├── Disassembler/
├── IR/
│   ├── snir_schema.json
│   └── v8_lifter.py
├── Parser/
├── Simplify/
├── Translate/
├── tools/
│   └── recover_from_snir.py
├── patches/
│   └── v8/
├── tests/
│   └── test_view8.py
├── AGENTS.md
└── docs/
    └── TECHNICAL_SPEC.md
```

## 5. Runtime Components

### 5.1 `decompiler.py`

Main CUI entry point.

Supported commands:

```text
detect
lift
recover
all
batch
```

Responsibilities:

- route user commands;
- call View8 with the correct Python runtime;
- detect V8 version hashes;
- resolve an existing `v8dasm` binary;
- run SNIR export and source-like recovery;
- report subprocess failures with stderr/stdout context.

`decompiler.py` does not build, patch, or download V8.

### 5.2 `view8.py`

View8-compatible parser/export driver. It consumes either cached bytecode plus
`v8dasm`, or already-disassembled text with `--disassembled`.

Supported export formats include:

```text
v8_opcode
translated
decompiled
snir
ir
```

`ir` is an alias-compatible path for SNIR-style JSON export.

### 5.3 `IR/v8_lifter.py`

SNIR v1 lifter. It converts parsed V8 disassembly functions into a structured
JSON document.

Current implementation level:

- parses operands and bytecode offsets;
- classifies reads/writes for accumulator, registers, arguments, constants,
  and contexts;
- classifies control flow;
- builds basic blocks and CFG successors/predecessors;
- emits semantic atoms;
- emits a provenance-backed fact store;
- emits value/state/control dependence edges;
- emits limited e-graph alternatives for arithmetic idioms;
- emits region, type, and high-level candidates.

This is a conservative lifting layer, not a complete high-level decompiler.
Unsupported or ambiguous opcodes are preserved through raw opcode, operands,
effects, access sets, facts, and provenance.

### 5.4 `tools/recover_from_snir.py`

Source-like recovery helper that reads SNIR JSON and emits JavaScript-like
output from constant pools.

Supported recovery kinds:

```text
auto
generic
settings
```

The recovery output is a reconstruction. It may preserve object literals,
strings, exports, and recognizable module shapes, but it cannot recover comments,
formatting, original local names, or exact source layout.

### 5.5 `v8_builder.py`

Maintainer/agent helper for building patched `v8dasm` binaries. It is not part
of the public decompiler CUI.

Agent-facing build policy is defined in:

```text
AGENTS.md
patches/v8/PATCH_GUIDE.md
```

## 6. Command Contracts

### 6.1 `detect`

```bash
python3 decompiler.py detect <input.jsc>
```

Output:

```json
{
  "input": "...",
  "hash": "00000000",
  "v8": "8.5.210.26",
  "error": null
}
```

Exit behavior:

- returns `0` when a V8 version is detected;
- returns `2` when the hash is read but not mapped to a known V8 version;
- returns `1` for unexpected runtime errors.

### 6.2 `lift`

```bash
python3 decompiler.py lift <input> <output> -f snir [--v8 <version>] [--v8dasm <path>]
python3 decompiler.py lift <disasm.txt> <output> -f snir --disassembled
```

Responsibilities:

- detect V8 version unless `--v8` is provided or `--disassembled` is used;
- resolve an existing `v8dasm` binary unless `--disassembled` is used;
- export the requested View8 format.

`lift` must not attempt to build missing `v8dasm` binaries.

### 6.3 `recover`

```bash
python3 decompiler.py recover <input.snir.json> <output.js> [--kind auto] [--check]
```

Responsibilities:

- load SNIR JSON;
- infer or accept recovery kind;
- emit source-like JavaScript;
- optionally syntax-check output with `node --check` when `--check` is used.
  Node.js must be installed for this mode.

### 6.4 `all`

```bash
python3 decompiler.py all <input.jsc> -o <out-dir> [--check] [--no-pseudo]
```

Pipeline:

```text
detect
  -> View8 SNIR export
  -> optional View8 pseudo JS export
  -> constant-pool recovery
```

Output files:

```text
<stem>.version.json
<stem>.snir.json
<stem>.pseudo.js
<stem>.constants.js
```

### 6.5 `batch`

```bash
python3 decompiler.py batch <input-dir> -o <out-dir> --glob '*.jsc' --keep-going
```

Runs the `all` pipeline over matching files. Each input gets its own output
directory based on the relative input path.

## 7. `v8dasm` Resolution

`decompiler.py` resolves helpers from `Bin`.

Selection rules:

1. If `--v8dasm <path>` is provided, that exact file must exist.
2. If a V8 version is known, prefer binaries whose filename starts with that
   version string.
3. Otherwise use the first `*v8dasm*` candidate in sorted order.
4. If no candidate exists, fail with `FileNotFoundError`.

Installed helper naming convention:

```text
Bin/<v8-version>-<platform>-v8dasm[.exe]
```

Example:

```text
Bin/8.5.210.26-mac-x64-v8dasm
```

## 8. SNIR v1 Data Model

SNIR means Semantic Neutral Intermediate Representation. In this repository,
SNIR v1 is a JSON representation designed to preserve facts and uncertainty
before high-level source projection.

Top-level document:

```json
{
  "schema": "view8-snir-document-v1",
  "functions": []
}
```

Function object required fields:

```text
schema
name
kind
declarer
argument_count
register_count
constant_pool
exception_table
semantic_atoms
fact_store
dependence_graph
egraph
region_candidates
type_hypotheses
high_level_candidates
blocks
```

The JSON Schema is stored at:

```text
IR/snir_schema.json
```

### 8.1 Semantic Atoms

Semantic atoms represent bytecode-level operations with provenance.

Atom fields:

```text
id
offset
opcode
raw
operands
reads
writes
effects
control_flow
provenance
semantics
```

The `semantics` field uses small P-Code/BIL-like operations where known, for
example:

```json
{"op": "assign", "dst": "ACCU", "src": {"kind": "immediate", "value": 2}}
{"op": "binary_op", "operator": "mul", "dst": "ACCU", "left": "ACCU", "right": {"kind": "register", "name": "r0"}}
{"op": "branch.conditional", "condition": "to_boolean(acc)", "target": 12}
```

When exact semantics are not implemented, the lifter still records access and
effect atoms such as:

```json
{"op": "acc.read", "name": "ACCU"}
{"op": "reg.write", "name": "r1"}
{"op": "effect.call"}
```

### 8.2 Fact Store

The fact store keeps inferred candidates with evidence and confidence.

Fact shape:

```json
{
  "id": "fact_0",
  "relation": "maybe_type",
  "subject": "ACCU",
  "value": "maybe_number",
  "confidence": 0.7,
  "evidence": []
}
```

Current relations include:

```text
maybe_function
constant_pool_entry
bytecode_instruction
maybe_loop
maybe_type
maybe_call
maybe_exception_region
```

Facts are intentionally monotonic. New analysis should add evidence-backed
candidates instead of deleting ambiguous information too early.

### 8.3 Basic Blocks

Blocks are derived from bytecode leaders, jump targets, fallthroughs, switches,
and exception handlers.

Block fields:

```text
id
start
end
instructions
successors
predecessors
exception_handlers
```

Successor edges preserve labels such as:

```text
fallthrough
jump
backedge
case:<n>
<condition>
```

### 8.4 Dependence Graph

The dependence graph contains:

- value edges for accumulator/register data flow;
- state edges for stateful effects and control boundaries;
- control edges for CFG successors and exception handlers.

Edge shape:

```json
{"kind": "value", "from": "atom_1", "to": "atom_3", "resource": "r0"}
{"kind": "state", "from": "atom_5", "to": "atom_9", "resource": "v8_state"}
{"kind": "control", "from": "atom_10", "to": "atom_14", "edge": "backedge", "target": 2}
```

This is RVSDG-inspired, but v1 is not a full RVSDG implementation.

### 8.5 E-Graph Candidates

The e-graph layer stores equivalent expression candidates for selected
arithmetic idioms.

Example:

```json
{
  "id": "eclass_0",
  "root": "atom_3",
  "members": [
    {"op": "shl", "args": ["ACCU", "1"]},
    {"op": "add", "args": ["ACCU", "ACCU"]},
    {"op": "mul", "args": ["ACCU", "2"]}
  ],
  "constraints": {
    "language": "javascript",
    "numeric_semantics": "unknown-number-or-bigint",
    "overflow": "not-applicable-to-js-number"
  }
}
```

v1 implements a small local equivalence set. Future work may replace this with
a real equality saturation engine.

### 8.6 Type and High-Level Candidates

`type_hypotheses` is a filtered view of `maybe_type` facts.

`high_level_candidates` is a filtered view of facts useful for source
projection:

```text
maybe_loop
maybe_exception_region
maybe_call
maybe_function
```

These are candidates, not final recovered source structures.

## 9. Recovery Semantics

Cached bytecode does not preserve exact source. Recovery must label its output
as reconstructed.

Allowed recovery inputs:

- constant-pool strings;
- object literal strings printed by V8;
- module/export names;
- function names preserved by bytecode metadata;
- bytecode and SNIR facts.

Disallowed claims:

- exact comments;
- exact formatting;
- original local variable names;
- exact authoring order when not proven by bytecode or constants.

## 10. Build and Patch Operations

`v8_builder.py` supports maintainer/agent workflows:

```bash
python3 v8_builder.py \
  --v8-version <version> \
  --build-v8dasm \
  --target-platform auto \
  --install-dir Bin
```

Patch order:

```text
Disassembler/v8.patch
patches/v8/common/*.patch
patches/v8/platform/<target-platform>/*.patch
patches/v8/<v8-version>/*.patch
patches/v8/<v8-version>/<target-platform>/*.patch
--patch-file <extra.patch>
```

Generated V8 source trees, build caches, extracted apps, SNIR exports, recovered
JavaScript, virtual environments, and Python caches must not be committed.

## 11. Testing Requirements

Required local checks:

```bash
python3 -m unittest tests/test_view8.py
python3 -m py_compile decompiler.py v8_builder.py tools/recover_from_snir.py
```

Current tests verify:

- V8 version hash helpers;
- SNIR fixture parsing;
- SNIR schema compatibility;
- exact semantic atoms for a sample arithmetic function;
- `ir` export alias compatibility;
- SNIR JSON to pseudo-JS decompilation path.

## 12. Compatibility Notes

Bundled helper currently present:

```text
Bin/8.5.210.26-mac-x64-v8dasm
```

Other V8/platform combinations require a matching helper binary prepared through
the maintainer/agent build flow.

## 13. Future Work

- Expand exact semantic atom coverage for V8 opcodes.
- Add formal SNIR version migration rules.
- Replace local e-graph candidates with a real equality saturation backend.
- Add stronger region structuring for loops, branches, switches, generators,
  async functions, and exception handlers.
- Improve type hypotheses with conflict tracking and evidence merging.
- Add fixture coverage for real bytenode/Electron modules across V8 versions.
- Add platform CI that validates `--disassembled` flows without requiring native
  `v8dasm`.
