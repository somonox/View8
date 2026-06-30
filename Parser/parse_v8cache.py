
import subprocess
import os
import platform
import sys
from Parser.sfi_file_parser import parse_file
from Parser.v8_version import detect_v8_version, VersionDetectionError


def get_version(_view8_dir, file_name):
    try:
        return detect_v8_version(file_name)
    except VersionDetectionError as e:
        raise RuntimeError(
            f"Failed to detect version for file {file_name}: {e} "
            "You can specify a path to a compatible disassembler using the --path (-p) argument."
        )


def run_disassembler_binary(binary_path, file_name, out_file_name):
    # Ensure the binary exists
    if not os.path.isfile(binary_path):
        raise FileNotFoundError(
            f"The binary '{binary_path}' does not exist. "
            "You can specify a path to a similar disassembler version using the --path (-p) argument."
        )

    # Open the output file in write mode
    with open(out_file_name, 'w') as outfile:
        # Call the binary with the file name as argument and pipe the output to the file
        try:
            result = subprocess.run([binary_path, file_name], stdout=outfile, stderr=subprocess.PIPE, text=True)

            # Check the return status code
            if result.stderr:
                raise RuntimeError(
                    f"Binary execution failed with status code {result.returncode}: {result.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error calling the binary: {e}")


def get_disassembler_candidates(version):
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        arch = machine

    if sys.platform == "darwin":
        platform_names = [f"mac-{arch}"]
        if arch != "x64":
            platform_names.append("mac-x64")
    elif sys.platform.startswith("linux"):
        platform_names = [f"linux-{arch}"]
    elif sys.platform.startswith("win"):
        platform_names = [f"win-{arch}"]
    else:
        platform_names = []

    candidates = []
    for platform_name in platform_names:
        candidates.append(f"{version}-{platform_name}-v8dasm")
        candidates.append(f"{version}-{platform_name}")
    candidates.extend([f"{version}.exe", version])
    return candidates


def resolve_disassembler_binary(view8_dir, version):
    bin_dir = os.path.join(view8_dir, 'Bin')
    candidates = [os.path.join(bin_dir, name) for name in get_disassembler_candidates(version)]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"No disassembler binary found for V8 {version}. Tried: "
        f"{', '.join(candidates)}. You can specify a compatible binary using the --path (-p) argument."
    )


def parse_v8cache_file(file_name, out_name, view8_dir, binary_path):
    if not binary_path:
        print(f"Detecting version.")
        version = get_version(view8_dir, file_name)
        print(f"Detected version: {version}.")
        binary_path = resolve_disassembler_binary(view8_dir, version)
    print(f"Executing disassembler binary: {binary_path}.")
    run_disassembler_binary(binary_path, file_name, out_name)
    print(f"Disassembly completed successfully.")


def parse_disassembled_file(out_name):
    print(f"Parsing disassembled file.")
    all_func = parse_file(out_name)
    print(f"Parsing completed successfully.")
    return all_func
