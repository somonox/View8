#!/usr/bin/env python3
"""
CUI front-end for the local V8 bytecode decompiler framework.

The tool wraps the pieces kept in this workspace:
- View8 parser/lifter/decompiler modules at the repository root
- bundled v8dasm binaries in Bin/
- Python version-hash detector
- constant-pool recovery helpers
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
VIEW8_SCRIPT = ROOT / "view8.py"
VIEW8_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
BIN_DIR = ROOT / "Bin"
RECOVER_SCRIPT = ROOT / "tools" / "recover_from_snir.py"


def python_for_view8() -> Path:
    if VIEW8_VENV_PYTHON.exists():
        return VIEW8_VENV_PYTHON
    return Path(sys.executable)


def run(cmd: list[str | os.PathLike[str]], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(str(x) for x in cmd)
    if not quiet:
        print(f"[*] {printable}")
    return subprocess.run(
        [str(x) for x in cmd],
        check=True,
        text=True,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
    )


def import_version_module():
    sys.path.insert(0, str(ROOT))
    from Parser.v8_version import (  # type: ignore
        VersionDetectionError,
        detect_v8_version,
        read_version_hash,
    )

    return VersionDetectionError, detect_v8_version, read_version_hash


def detect_version(input_file: Path) -> dict[str, Any]:
    VersionDetectionError, detect_v8_version, read_version_hash = import_version_module()
    version_hash = read_version_hash(str(input_file))
    result: dict[str, Any] = {
        "input": str(input_file),
        "hash": f"{version_hash:08x}",
        "v8": None,
        "error": None,
    }
    try:
        result["v8"] = detect_v8_version(str(input_file))
    except VersionDetectionError as error:
        result["error"] = str(error)
    return result


def find_v8dasm(version: str | None = None, explicit: Path | None = None) -> Path:
    if explicit:
        if not explicit.exists():
            raise FileNotFoundError(f"v8dasm not found: {explicit}")
        return explicit

    candidates = sorted(BIN_DIR.glob("*v8dasm*"))
    if version:
        exact = [p for p in candidates if p.name.startswith(version)]
        if exact:
            return exact[0]

    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No v8dasm binary found in {BIN_DIR}")


def view8_export(
    input_file: Path,
    output_file: Path,
    export_format: str,
    *,
    v8dasm: Path | None,
    disassembled: bool = False,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str | os.PathLike[str]] = [
        python_for_view8(),
        VIEW8_SCRIPT,
        input_file,
        output_file,
        "--export_format",
        export_format,
    ]
    if v8dasm and not disassembled:
        cmd.extend(["--path", v8dasm])
    if disassembled:
        cmd.append("--disassembled")
    run(cmd)


def recover_from_snir(snir_file: Path, output_file: Path, *, kind: str, source_label: str | None, check: bool) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str | os.PathLike[str]] = [
        sys.executable,
        RECOVER_SCRIPT,
        snir_file,
        "--out",
        output_file,
        "--kind",
        kind,
    ]
    if source_label:
        cmd.extend(["--source-label", source_label])
    if check:
        cmd.append("--check")
    run(cmd)


def command_detect(args: argparse.Namespace) -> int:
    info = detect_version(args.input)
    print(json.dumps(info, indent=2))
    return 0 if info.get("v8") else 2


def command_lift(args: argparse.Namespace) -> int:
    version = args.v8
    if not version and not args.disassembled:
        info = detect_version(args.input)
        version = info.get("v8")
        if info.get("error"):
            print(f"[!] Version detection warning: {info['error']}")
    v8dasm = None if args.disassembled else find_v8dasm(version, args.v8dasm)
    view8_export(args.input, args.output, args.format, v8dasm=v8dasm, disassembled=args.disassembled)
    return 0


def command_recover(args: argparse.Namespace) -> int:
    recover_from_snir(args.snir, args.output, kind=args.kind, source_label=args.source_label, check=args.check)
    return 0


def command_all(args: argparse.Namespace) -> int:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = args.input.stem
    info = detect_version(args.input)
    (out_dir / f"{stem}.version.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    if info.get("error"):
        print(f"[!] Version detection warning: {info['error']}")

    version = args.v8 or info.get("v8")
    v8dasm = find_v8dasm(version, args.v8dasm)
    print(f"[*] Using v8dasm: {v8dasm}")

    snir_out = out_dir / f"{stem}.snir.json"
    pseudo_out = out_dir / f"{stem}.pseudo.js"
    constants_out = out_dir / f"{stem}.constants.js"

    view8_export(args.input, snir_out, "snir", v8dasm=v8dasm)
    if not args.no_pseudo:
        view8_export(args.input, pseudo_out, "decompiled", v8dasm=v8dasm)
    recover_from_snir(
        snir_out,
        constants_out,
        kind=args.kind,
        source_label=args.source_label or str(args.input),
        check=args.check,
    )

    print(json.dumps({
        "input": str(args.input),
        "out_dir": str(out_dir),
        "version": str(out_dir / f"{stem}.version.json"),
        "snir": str(snir_out),
        "pseudo": None if args.no_pseudo else str(pseudo_out),
        "recovered_constants": str(constants_out),
    }, indent=2))
    return 0


def command_batch(args: argparse.Namespace) -> int:
    inputs = sorted(args.input_dir.rglob(args.glob))
    if not inputs:
        print(f"[!] No files matched {args.input_dir}/{args.glob}")
        return 1

    failures = 0
    for input_file in inputs:
        rel = input_file.relative_to(args.input_dir)
        module_out = args.out_dir / rel.with_suffix("")
        print(f"\n=== {rel} ===")
        ns = argparse.Namespace(
            input=input_file,
            out_dir=module_out,
            v8=args.v8,
            v8dasm=args.v8dasm,
            kind=args.kind,
            source_label=str(rel),
            check=args.check,
            no_pseudo=args.no_pseudo,
        )
        try:
            command_all(ns)
        except Exception as error:
            failures += 1
            print(f"[!] Failed {rel}: {error}")
            if not args.keep_going:
                raise
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="decompiler.py",
        description="CUI decompiler for V8/bytenode cached bytecode.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("detect", help="Read bytecode header and detect V8 version")
    p.add_argument("input", type=Path)
    p.set_defaults(func=command_detect)

    p = sub.add_parser("lift", help="Export one View8 format")
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("-f", "--format", choices=["v8_opcode", "translated", "decompiled", "snir", "ir"], default="snir")
    p.add_argument("--v8", help="Override detected V8 version")
    p.add_argument("--v8dasm", type=Path, help="Explicit v8dasm binary")
    p.add_argument("--disassembled", action="store_true", help="Input is already v8dasm text")
    p.set_defaults(func=command_lift)

    p = sub.add_parser("recover", help="Recover JS-like constants from SNIR")
    p.add_argument("snir", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--kind", choices=["auto", "generic", "settings"], default="auto")
    p.add_argument("--source-label")
    p.add_argument("--check", action="store_true")
    p.set_defaults(func=command_recover)

    p = sub.add_parser("all", help="Run detect + SNIR + pseudo + constant recovery")
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--out-dir", type=Path, required=True)
    p.add_argument("--v8", help="Override detected V8 version")
    p.add_argument("--v8dasm", type=Path, help="Explicit v8dasm binary")
    p.add_argument("--kind", choices=["auto", "generic", "settings"], default="auto")
    p.add_argument("--source-label")
    p.add_argument("--check", action="store_true")
    p.add_argument("--no-pseudo", action="store_true")
    p.set_defaults(func=command_all)

    p = sub.add_parser("batch", help="Run all over an input directory")
    p.add_argument("input_dir", type=Path)
    p.add_argument("-o", "--out-dir", type=Path, required=True)
    p.add_argument("--glob", default="*.jsc")
    p.add_argument("--v8", help="Override detected V8 version")
    p.add_argument("--v8dasm", type=Path, help="Explicit v8dasm binary")
    p.add_argument("--kind", choices=["auto", "generic", "settings"], default="auto")
    p.add_argument("--check", action="store_true")
    p.add_argument("--no-pseudo", action="store_true")
    p.add_argument("--keep-going", action="store_true")
    p.set_defaults(func=command_batch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as error:
        print(f"[!] Command failed with exit code {error.returncode}: {error.cmd}", file=sys.stderr)
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        return error.returncode
    except Exception as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
