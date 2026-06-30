import json
import re
import ssl
import struct
import urllib.error
import urllib.request


NODE_RELEASES_URL = "https://nodejs.org/dist/index.json"
ELECTRON_RELEASES_URL = "https://releases.electronjs.org/releases.json"


class VersionDetectionError(RuntimeError):
    pass


def hash_value_unsigned(value):
    value = ((value << 15) - value - 1) & 0xFFFFFFFF
    value = (value ^ (value >> 12)) & 0xFFFFFFFF
    value = (value + (value << 2)) & 0xFFFFFFFF
    value = (value ^ (value >> 4)) & 0xFFFFFFFF
    value = (value * 2057) & 0xFFFFFFFF
    value = (value ^ (value >> 16)) & 0xFFFFFFFF
    return value


def hash_combine64(seed, value):
    multiplier = 0xC6A4A7935BD1E995
    shift = 47

    value = (value * multiplier) & 0xFFFFFFFFFFFFFFFF
    value = (value ^ (value >> shift)) & 0xFFFFFFFFFFFFFFFF
    value = (value * multiplier) & 0xFFFFFFFFFFFFFFFF

    seed = (seed ^ value) & 0xFFFFFFFFFFFFFFFF
    seed = (seed * multiplier) & 0xFFFFFFFFFFFFFFFF
    return seed


def version_hash64(major, minor, build, patch=0):
    seed = 0
    seed = hash_combine64(seed, hash_value_unsigned(patch))
    seed = hash_combine64(seed, hash_value_unsigned(build))
    seed = hash_combine64(seed, hash_value_unsigned(minor))
    seed = hash_combine64(seed, hash_value_unsigned(major))
    return seed & 0xFFFFFFFF


def read_bytecode_header(file_name):
    with open(file_name, "rb") as file:
        header = file.read(8)

    if len(header) < 8:
        raise VersionDetectionError("Invalid file signature: file is smaller than 8 bytes.")

    return struct.unpack("<II", header)


def check_signature(magic_number):
    return magic_number >> 16 == 0xC0DE


def read_version_hash(file_name):
    magic_number, version_hash = read_bytecode_header(file_name)
    if not check_signature(magic_number):
        raise VersionDetectionError("Invalid file signature.")
    return version_hash


def normalize_v8_version(version):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        raise ValueError(f"Invalid V8 version: {version}")

    parts = [int(part) if part is not None else 0 for part in match.groups()]
    return parts, ".".join(str(part) for part in parts)


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "View8"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise

    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        return json.load(response)


def add_release(versions, release_type, runtime_version, v8_version):
    version_parts, normalized_v8_version = normalize_v8_version(v8_version)
    versions.append({
        "type": release_type,
        "version": runtime_version.lstrip("v"),
        "v8": normalized_v8_version,
        "hash": version_hash64(*version_parts),
    })
    versions.append({
        "type": release_type,
        "version": runtime_version.lstrip("v"),
        "v8": normalized_v8_version,
        "hash": version_hash64(*reversed(version_parts)),
    })


def fetch_versions():
    versions = []
    node_versions = fetch_json(NODE_RELEASES_URL)
    electron_versions = fetch_json(ELECTRON_RELEASES_URL)

    for release in node_versions:
        if release.get("v8"):
            add_release(versions, "node", release["version"], release["v8"])

    for release in electron_versions:
        if release.get("v8"):
            add_release(versions, "electron", release["version"], release["v8"])

    return versions


def find_versions(version_hash, versions=None):
    versions = versions if versions is not None else fetch_versions()
    return [release for release in versions if release["hash"] == version_hash]


def detect_v8_version(file_name):
    version_hash = read_version_hash(file_name)
    try:
        matches = find_versions(version_hash)
    except Exception as error:
        raise VersionDetectionError(f"Failed to fetch V8 version metadata: {error}") from error

    if not matches:
        hash_hex = f"{version_hash:08x}"
        raise VersionDetectionError(f"No matching V8 version found for hash {hash_hex}.")

    return matches[0]["v8"]
