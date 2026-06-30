import argparse
import platform
import shutil
import subprocess
import os
from pathlib import Path


def normalize_host_platform():
    os_type = platform.system().lower()
    arch = platform.machine().lower()
    if os_type == "darwin":
        return "mac-arm64" if arch in ["arm64", "aarch64"] else "mac-x64"
    if os_type == "windows":
        return "win-x64"
    if os_type == "linux":
        return "linux-arm64" if arch in ["arm64", "aarch64"] else "linux-x64"
    return f"{os_type}-{arch}"


def parse_target_platform(target_platform):
    if target_platform in (None, "auto"):
        target_platform = normalize_host_platform()

    aliases = {
        "darwin-x64": "mac-x64",
        "darwin-arm64": "mac-arm64",
        "macos-x64": "mac-x64",
        "macos-arm64": "mac-arm64",
        "windows-x64": "win-x64",
    }
    target_platform = aliases.get(target_platform, target_platform)

    parts = target_platform.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid target platform: {target_platform}")

    target_os, target_arch = parts
    if target_os not in ["mac", "win", "linux"]:
        raise ValueError(f"Unsupported target OS: {target_os}")
    if target_arch not in ["x64", "arm64"]:
        raise ValueError(f"Unsupported target arch: {target_arch}")
    return target_platform, target_os, target_arch

class V8BuilderFramework:
    def __init__(
        self,
        target_version,
        build_dir,
        build_v8dasm,
        v8dasm_src,
        target_platform="auto",
        patch_files=None,
        apply_default_patches=True,
    ):
        self.v8_version = target_version
        self.build_dir = os.path.abspath(build_dir)
        self.depot_tools_dir = os.path.join(self.build_dir, "depot_tools")
        self.v8_source_dir = os.path.join(self.build_dir, "v8")
        self.build_v8dasm_flag = build_v8dasm
        self.v8dasm_src = os.path.abspath(v8dasm_src) if v8dasm_src else None
        self.repo_root = os.path.abspath(os.path.dirname(__file__))
        self.patch_files = [os.path.abspath(str(p)) for p in (patch_files or [])]
        self.apply_default_patches = apply_default_patches
        self.target_platform, self.target_os, self.target_arch = parse_target_platform(target_platform)
        
        self.os_type = platform.system().lower()  # darwin, linux, windows
        self.arch = platform.machine().lower()      # x86_64, arm64, amd64
        self.host_platform = normalize_host_platform()
        
        # Check if we are running on Apple Silicon macOS
        self.is_mac_arm64 = (self.os_type == "darwin" and self.arch == "arm64")
        self.force_mac_x64_on_arm64 = self.host_platform == "mac-arm64" and self.target_platform == "mac-x64"
        
        # Normalize arch names
        if self.force_mac_x64_on_arm64:
            # Force x64 target and instruct CIPD to download x64 toolchains
            self.cpu_target = "x64"
            os.environ["CIPD_FORCE_PLATFORM"] = "mac-amd64"
            os.environ["CIPD_FORCE_ARCH"] = "amd64"
        else:
            self.cpu_target = self.target_arch

        if self.target_os == "win":
            self.gn_target_os = "win"
        elif self.target_os == "mac":
            self.gn_target_os = "mac"
        else:
            self.gn_target_os = "linux"

    @property
    def executable_suffix(self):
        return ".exe" if self.target_os == "win" else ""

    @property
    def output_binary_name(self):
        return f"{self.v8_version}-{self.target_platform}-v8dasm{self.executable_suffix}"

    def validate_target_support(self, allow_cross=False):
        if self.target_platform == self.host_platform:
            return
        if self.force_mac_x64_on_arm64:
            return
        if allow_cross:
            print(f"[!] Cross target requested: host={self.host_platform}, target={self.target_platform}")
            print("[!] This only works when your local V8/Chromium toolchain supports that target.")
            return
        raise RuntimeError(
            f"Target {self.target_platform} does not match host {self.host_platform}. "
            "Use the matching OS host, or pass --allow-cross if you have a configured cross toolchain."
        )

    def run_cmd(self, cmd, **kwargs):
        # Run commands natively; toolchain architectures are managed via CIPD_FORCE_ARCH
        return subprocess.run(cmd, **kwargs)

    def discover_patch_files(self):
        patches = []
        if self.apply_default_patches:
            default_patch = os.path.join(self.repo_root, "View8", "Disassembler", "v8.patch")
            if os.path.isfile(default_patch):
                patches.append(default_patch)

            patch_root = os.path.join(self.repo_root, "patches", "v8")
            search_dirs = [
                os.path.join(patch_root, "common"),
                os.path.join(patch_root, "platform", self.target_platform),
                os.path.join(patch_root, self.v8_version),
                os.path.join(patch_root, self.v8_version, self.target_platform),
            ]
            for directory in search_dirs:
                if os.path.isdir(directory):
                    for patch_file in sorted(Path(directory).glob("*.patch")):
                        patches.append(str(patch_file))

        patches.extend(self.patch_files)
        deduped = []
        seen = set()
        for patch_file in patches:
            real = os.path.abspath(patch_file)
            if real not in seen:
                seen.add(real)
                deduped.append(real)
        return deduped

    def apply_source_patches(self):
        patch_files = self.discover_patch_files()
        if not patch_files:
            print("[*] No V8 source patches configured.")
            return True

        orig_cwd = os.getcwd()
        os.chdir(self.v8_source_dir)
        try:
            for patch_file in patch_files:
                if not os.path.isfile(patch_file):
                    raise FileNotFoundError(f"Patch file not found: {patch_file}")

                print(f"[*] Applying patch: {patch_file}")
                check = self.run_cmd(["git", "apply", "--check", patch_file])
                if check.returncode == 0:
                    self.run_cmd(["git", "apply", patch_file], check=True)
                    continue

                reverse_check = self.run_cmd(["git", "apply", "--reverse", "--check", patch_file])
                if reverse_check.returncode == 0:
                    print(f"[*] Patch already applied, skipping: {patch_file}")
                    continue

                raise RuntimeError(
                    f"Patch does not apply cleanly for V8 {self.v8_version} "
                    f"target {self.target_platform}: {patch_file}"
                )
            return True
        finally:
            os.chdir(orig_cwd)



    def setup_directories(self):
        print(f"[*] Setting up build directories in: {self.build_dir}")
        os.makedirs(self.build_dir, exist_ok=True)

    def install_depot_tools(self):
        if os.path.isdir(self.depot_tools_dir):
            print("[+] depot_tools already exists. Skipping download.")
            if self.force_mac_x64_on_arm64:
                override_file = os.path.join(self.depot_tools_dir, ".cipd_client_platform")
                with open(override_file, "w") as f:
                    f.write("mac-amd64\n")
                print("[*] Ensured .cipd_client_platform override file exists with 'mac-amd64'.")
            return True
        
        print("[*] Downloading Google depot_tools...")
        depot_url = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
        
        try:
            # Clone depot_tools
            cmd = ["git", "clone", "--depth", "1", depot_url, self.depot_tools_dir]
            self.run_cmd(cmd, check=True)
            print("[+] depot_tools successfully cloned.")
            
            if self.force_mac_x64_on_arm64:
                override_file = os.path.join(self.depot_tools_dir, ".cipd_client_platform")
                with open(override_file, "w") as f:
                    f.write("mac-amd64\n")
                print("[*] Created .cipd_client_platform override file with 'mac-amd64'.")
                
            return True
        except Exception as e:
            print(f"[-] Error installing depot_tools: {e}")
            return False


    def update_environment_path(self):
        # Prepend depot_tools to the search path
        os.environ["PATH"] = self.depot_tools_dir + os.pathsep + os.environ["PATH"]
        # Required to bypass some interactive prompts for depot_tools
        os.environ["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
        print("[*] Environment PATH updated to include depot_tools.")

    def checkout_v8_source(self):
        print(f"[*] Fetching V8 source code for version {self.v8_version}...")
        
        # We need to run inside the build directory
        orig_cwd = os.getcwd()
        os.chdir(self.build_dir)
        
        try:
            # Check if V8 repository is already fetched
            if not os.path.isdir(self.v8_source_dir):
                # Remove stale .gclient if it exists (leftover from failed fetch)
                gclient_file = os.path.join(self.build_dir, ".gclient")
                if os.path.isfile(gclient_file):
                    os.remove(gclient_file)
                    print("[*] Removed stale .gclient file from previous attempt.")
                
                print("[*] Running fetch v8 (this may take a few minutes)...")
                fetch_cmd = ["fetch", "v8"]
                self.run_cmd(fetch_cmd, check=True)

            
            # Navigate to v8 directory
            os.chdir(self.v8_source_dir)
            
            # Fetch all tags and checkout specified version
            print(f"[*] Checking out V8 tag: {self.v8_version}")
            self.run_cmd(["git", "fetch", "--tags"], check=True)
            self.run_cmd(["git", "checkout", self.v8_version], check=True)
            
            # Patch DEPS to remove CIPD packages that don't exist for mac-arm64
            # on older V8 branches (luci/isolate, luci/isolated, luci/swarming)
            if self.force_mac_x64_on_arm64:
                self._patch_deps_remove_missing_cipd()
            
            # Synchronize V8 dependencies
            print("[*] Running gclient sync (downloading toolchains & submodules)...")
            # Set network resilience env vars
            os.environ["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"
            os.environ["GIT_HTTP_LOW_SPEED_TIME"] = "60"
            gclient_cmd = ["gclient", "sync", "-D", "--force", "--no-history"]
            self.run_cmd(gclient_cmd, check=True)
            
            print("[+] V8 source sync completed successfully.")
            os.chdir(orig_cwd)
            return True
        except Exception as e:
            print(f"[-] Failed to checkout V8 source: {e}")
            os.chdir(orig_cwd)
            return False

    def _patch_deps_remove_missing_cipd(self):
        """Remove CIPD luci packages from DEPS that don't have mac-arm64 tags."""
        deps_path = os.path.join(self.v8_source_dir, "DEPS")
        if not os.path.isfile(deps_path):
            print("[!] DEPS file not found, skipping patch.")
            return
        
        with open(deps_path, "r") as f:
            content = f.read()
        
        # Remove the 3 problematic luci CIPD package entries
        import re
        # Match CIPD package dict entries for isolate, isolated, swarming
        patterns = [
            r"\s*\{\s*\n\s*'package':\s*'infra/tools/luci/isolate/\$\{\{platform\}\}',\s*\n\s*'version':.*?\n\s*\},?",
            r"\s*\{\s*\n\s*'package':\s*'infra/tools/luci/isolated/\$\{\{platform\}\}',\s*\n\s*'version':.*?\n\s*\},?",
            r"\s*\{\s*\n\s*'package':\s*'infra/tools/luci/swarming/\$\{\{platform\}\}',\s*\n\s*'version':.*?\n\s*\},?",
        ]
        
        patched = content
        for pattern in patterns:
            patched = re.sub(pattern, "", patched)
        
        if patched != content:
            with open(deps_path, "w") as f:
                f.write(patched)
            print("[*] Patched DEPS: removed luci/isolate, luci/isolated, luci/swarming CIPD entries.")
        else:
            print("[*] DEPS file already clean or patterns not found.")


    def configure_gn_args(self):
        print("[*] Generating GN build configuration...")
        out_dir = os.path.join(self.v8_source_dir, "out.gn", "v8_monolith")
        os.makedirs(out_dir, exist_ok=True)
        
        gn_args = [
            "is_debug = false",
            "is_component_build = false",
            "v8_monolithic = true",
            "v8_use_external_startup_data = false",
            "symbol_level = 0",
            f"target_os = \"{self.gn_target_os}\"",
            f"target_cpu = \"{self.cpu_target}\"",
        ]
        
        # Platform specific options
        if self.os_type in ["darwin", "linux"]:
            # Prevents linking issues between custom libc++ and system libraries
            gn_args.append("use_custom_libcxx = false")
        
        if self.target_os == "mac":
            # Set target sdk version or override clang if arm64 mac
            gn_args.append("treat_warnings_as_errors = false")
            
        args_file_path = os.path.join(out_dir, "args.gn")
        with open(args_file_path, "w") as f:
            f.write("\n".join(gn_args))
            f.write("\n")
            
        print(f"[+] GN args written to {args_file_path}:")
        for arg in gn_args:
            print(f"  {arg}")
            
        # Run gn gen
        orig_cwd = os.getcwd()
        os.chdir(self.v8_source_dir)
        try:
            gn_gen_cmd = ["gn", "gen", "out.gn/v8_monolith"]
            self.run_cmd(gn_gen_cmd, check=True)
            print("[+] GN configuration generated successfully.")
            os.chdir(orig_cwd)
            return True
        except Exception as e:
            print(f"[-] Error running gn gen: {e}")
            os.chdir(orig_cwd)
            return False

    def build_monolith(self):
        print("[*] Building v8_monolith targets (this will consume high CPU resources)...")
        orig_cwd = os.getcwd()
        os.chdir(self.v8_source_dir)
        
        try:
            # Build using ninja
            ninja_cmd = ["ninja", "-C", "out.gn/v8_monolith", "v8_monolith"]
            self.run_cmd(ninja_cmd, check=True)
            
            # Find built lib file
            lib_ext = ".lib" if self.target_os == "win" else ".a"
            built_lib = os.path.join(self.v8_source_dir, "out.gn", "v8_monolith", f"obj/libv8_monolith{lib_ext}")
            
            if not os.path.isfile(built_lib):
                # Fallback location for some V8 versions
                built_lib = os.path.join(self.v8_source_dir, "out.gn", "v8_monolith", f"libv8_monolith{lib_ext}")
                
            if os.path.isfile(built_lib):
                print(f"[+] Successfully built V8 monolithic library: {built_lib}")
                os.chdir(orig_cwd)
                return built_lib
            else:
                print("[-] Build finished but could not locate monolithic output library file.")
                os.chdir(orig_cwd)
                return None
        except Exception as e:
            print(f"[-] Error during Ninja build: {e}")
            os.chdir(orig_cwd)
            return None

    def compile_v8dasm_binary(self, monolith_path):
        if not self.build_v8dasm_flag or not self.v8dasm_src:
            print("[*] Custom v8dasm build not requested. Skipping compilation step.")
            return True
            
        print(f"[*] Initiating compilation for v8dasm using source: {self.v8dasm_src}")
        
        v8_include_dir = os.path.join(self.v8_source_dir, "include")
        output_binary = os.path.join(self.build_dir, "v8dasm.exe" if self.target_os == "win" else "v8dasm")
        
        try:
            if self.target_os == "win":
                # Build with MSVC (cl.exe)
                cl_cmd = [
                    "cl.exe", "/EHsc", "/O2", "/std:c++17",
                    f"/I{v8_include_dir}",
                    self.v8dasm_src,
                    monolith_path,
                    "winmm.lib", "dbghelp.lib", "shlwapi.lib",
                    f"/Fe{output_binary}"
                ]
                print(f"[*] Executing Windows MSVC Build command: {' '.join(cl_cmd)}")
                subprocess.run(cl_cmd, check=True)
            else:
                # Build with clang++ (macOS) or g++ (Linux)
                compiler = "clang++" if self.target_os == "mac" else "g++"
                compile_cmd = [
                    compiler, "-O3", "-std=c++17",
                    f"-I{v8_include_dir}",
                    self.v8dasm_src,
                    monolith_path,
                    "-lpthread"
                ]
                
                # Platform-specific link additions
                if self.target_os == "mac":
                    # macOS framework references
                    compile_cmd.extend(["-framework", "CoreFoundation"])
                    if self.force_mac_x64_on_arm64:
                        compile_cmd.extend(["-arch", "x86_64"])
                elif self.target_os == "linux":
                    # Linux realtime/dl linkages
                    compile_cmd.extend(["-lrt", "-ldl"])
                    
                compile_cmd.extend(["-o", output_binary])
                
                print(f"[*] Executing POSIX Build command: {' '.join(compile_cmd)}")
                self.run_cmd(compile_cmd, check=True)
                
            print(f"[+] Successfully compiled native v8dasm binary: {output_binary}")
            return output_binary
        except Exception as e:
            print(f"[-] Failed to compile v8dasm: {e}")
            return None

    def run_all(self):
        self.setup_directories()
        
        if not self.install_depot_tools():
            return None
            
        self.update_environment_path()
        
        if not self.checkout_v8_source():
            return None

        if not self.apply_source_patches():
            return None
            
        if not self.configure_gn_args():
            return None
            
        lib_path = self.build_monolith()
        if not lib_path:
            return None
            
        binary_path = self.compile_v8dasm_binary(lib_path)
        print("\n[+] V8 Builder process completed successfully!")
        return binary_path

    def run_and_install(self, install_dir, clean_build=False, allow_cross=False):
        self.validate_target_support(allow_cross=allow_cross)
        binary_path = self.run_all()
        if not binary_path:
            raise RuntimeError("v8dasm build failed")

        os.makedirs(install_dir, exist_ok=True)
        installed_path = os.path.join(os.path.abspath(install_dir), self.output_binary_name)
        shutil.copy2(binary_path, installed_path)
        if self.target_os != "win":
            os.chmod(installed_path, 0o755)
        print(f"[+] Installed v8dasm: {installed_path}")

        if clean_build:
            print(f"[*] Removing build directory: {self.build_dir}")
            shutil.rmtree(self.build_dir, ignore_errors=True)
        return installed_path


def main():
    parser = argparse.ArgumentParser(description="V8 Monolith Builder & v8dasm Compiler Framework")
    parser.add_argument("--v8-version", required=True, help="Target V8 version tag (e.g. 9.4.146.24)")
    parser.add_argument("--build-dir", default="./v8_build_sandbox", help="Sandbox build directory")
    parser.add_argument("--build-v8dasm", action="store_true", help="Compile native v8dasm binary after building V8")
    parser.add_argument("--v8dasm-source", default="./Disassembler/v8dasm.cpp", help="Path to v8dasm.cpp source file")
    parser.add_argument("--target-platform", default="auto", help="auto, mac-x64, mac-arm64, win-x64, linux-x64, linux-arm64")
    parser.add_argument("--patch-file", action="append", default=[], help="Extra V8 source patch file; can be repeated")
    parser.add_argument("--no-default-patches", action="store_true", help="Do not apply default/discovered V8 source patches")
    parser.add_argument("--install-dir", help="Copy final v8dasm into this directory")
    parser.add_argument("--clean-build", action="store_true", help="Remove build directory after installing v8dasm")
    parser.add_argument("--allow-cross", action="store_true", help="Allow non-host target when toolchain is configured")
    
    args = parser.parse_args()
    
    builder = V8BuilderFramework(
        target_version=args.v8_version,
        build_dir=args.build_dir,
        build_v8dasm=args.build_v8dasm,
        v8dasm_src=args.v8dasm_source,
        target_platform=args.target_platform,
        patch_files=args.patch_file,
        apply_default_patches=not args.no_default_patches,
    )
    if args.install_dir:
        builder.run_and_install(args.install_dir, clean_build=args.clean_build, allow_cross=args.allow_cross)
    else:
        builder.validate_target_support(allow_cross=args.allow_cross)
        builder.run_all()

if __name__ == "__main__":
    main()
