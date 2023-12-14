#!/usr/bin/env python3
import glob
import os
import re
import shutil
import subprocess
import tarfile
from contextlib import contextmanager
from typing import List, Tuple

from libs.io_helper import NetworkIOHelper, Paths
from libs.system_helper import Architecture


class NixPackagePathNotFoundError(Exception):
    pass


class NixBuildError(Exception):
    pass


class NixHelper:
    fwdproxy = True
    # Nix binary paths
    nix = os.path.join(Paths.NIX_BIN, "nix")
    nix_env = os.path.join(Paths.NIX_BIN, "nix-env")
    nix_store = os.path.join(Paths.NIX_BIN, "nix-store")

    # Call nix-env with an argument and capture its output
    def _nix_env_shell_out(self, arguments: str) -> str:
        with self._set_enviromentals():
            result = subprocess.run([self.nix_env, arguments], capture_output=True)
        return result.stdout.decode("utf-8")

    # Returns a list of remote nix packages
    def get_all_remote_packages(self) -> List[str]:
        package_list = self._nix_env_shell_out("-qa")
        return package_list.split()

    # Set enviromental variables for nix
    @contextmanager
    def _set_enviromentals(self, force_build: bool = False):
        saved = dict(os.environ)
        # See https://github.com/NixOS/nix/blob/master/tests/common.sh.in
        os.environ["NIX_STORE_DIR"] = Paths.NIX_STORE
        os.environ["NIX_STATE_DIR"] = Paths.NIX_STATE
        os.environ["NIX_LOG_DIR"] = Paths.NIX_LOG
        os.environ["NIX_CONF_DIR"] = Paths.NIX_CONFIG
        os.environ["NIX_SSL_CERT_FILE"] = (
            Paths.CA_PACKAGE + "/etc/ssl/certs/ca-bundle.crt"
        )

        nix_link = f"{os.environ['HOME']}/.nix-profile"
        os.environ["NIX_PATH"] = f"{os.environ['HOME']}/.nix-defexpr/channels"
        os.environ[
            "NIX_PROFILES"
        ] = f"{Paths.NIX_PROFILES}/default {os.environ['HOME']}/.nix-profile"
        os.environ["PATH"] = f"{nix_link}/bin:{os.environ['PATH']}"
        os.environ["NIXPKGS_ALLOW_UNFREE"] = "1"  # Permits proprietary/unfree packages
        if force_build:
            # This shouldn't be the default, but some packages
            # just have to be built. It also helps with getting logs
            # for WHY a package is failing.
            os.environ["NIXPKGS_ALLOW_INSECURE"] = "1"
            os.environ["NIXPKGS_ALLOW_UNSUPPORTED_SYSTEM"] = "1"
            os.environ["NIXPKGS_ALLOW_BROKEN"] = "1"

        if self.fwdproxy:
            self._set_fwdproxy_enviromentals()
        yield
        # Restore previous enviromental vars state
        os.environ.clear()
        os.environ.update(saved)

    # Additional enviromental vars for nix binaries to fetch under fwdproxy
    def _set_fwdproxy_enviromentals(self) -> None:
        # TODO Should this be part of the program? If so, change to SSL.
        os.environ["no_proxy"] = (
            ".fbcdn.net,.facebook.com,.thefacebook.com,"
            ".tfbnw.net,.fb.com,.fburl.com,.facebook.net,.sb.fbsbx.com,localhost"
        )
        os.environ["http_proxy"] = "fwdproxy:8080"
        os.environ["https_proxy"] = "fwdproxy:8080"
        os.environ["ftp_proxy"] = "fwdproxy:8080"
        os.environ["CURL_NIX_FLAGS"] = "-x http://fwdproxy:8080 --proxy-insecure"

    def _patch_bootstrap(self, nix_repo_root: str) -> bool:
        # Patch the bootstrap to not fail on binary patching failures
        to_patch = [
            'install_name_tool -id "$(dirname $i)/$(basename $id)" $i',
            "install_name_tool -add_rpath $out/lib $i",
        ]
        print("Patching unpack-bootstrap-tools.sh")

        script_path = f"{nix_repo_root}/pkgs/stdenv/darwin/unpack-bootstrap-tools.sh"
        patched_bootstrap_script = []
        patched = False
        with open(script_path, "r") as file:
            for line in file:
                new_line = line
                for target in to_patch:
                    if target in line and "|| true" not in line:
                        new_line = f"{line.rstrip()} || true\n"
                        print(f"Patching: {line.rstrip()}")
                        print(f"--> {new_line.rstrip()}")
                        patched = True
                patched_bootstrap_script.append(new_line)

        with open(script_path, "w") as f:
            for line in patched_bootstrap_script:
                f.writelines(line)
        return patched

    # Run the setup commands for the nix binaries
    def initial_setup(self, extractedpath: str) -> None:
        # Equivalent to source nix.sh
        with self._set_enviromentals():
            # Load DB
            with open(os.path.join(extractedpath, ".reginfo")) as regin:
                subprocess.run([self.nix_store, "--load-db"], stdin=regin)
            # Setup profile
            subprocess.run([self.nix_env, "-i", Paths.NIX_PACKAGE])
            # SSL
            subprocess.run([self.nix_env, "-i", Paths.CA_PACKAGE])
            # Show version
            subprocess.run([self.nix_env, "--version"])

    # Is nix2rpm prepared?
    def is_installed(self) -> bool:
        current_nix_installed = os.path.exists(Paths.NIX_PACKAGE)
        nix_profile_present = os.path.islink(os.path.expanduser("~/.nix-profile"))
        return current_nix_installed and nix_profile_present

    # Return list of pkgs matching searchterm from all nix pkgs
    def search(self, term: str) -> List[str]:
        packages = self.get_all_remote_packages()
        rank = []
        for package in packages:
            if term in package:
                rank.append(package)
        sorted_rank = sorted(rank, key=lambda x: len(x))
        return sorted_rank

    # Switch to a new profile to prevent reactions with prior installed packages
    def switch_profile(self, name: str) -> None:
        profile_path = os.path.join(Paths.NIX_PROFILES, "nix2rpm_" + name)
        with self._set_enviromentals():
            subprocess.run([self.nix_env, "--switch-profile", profile_path])

    # Shell out to nix to install a package, returns package name
    def build_pkg(
        self,
        pkg_name: str,
        force: bool = False,
        repo: str = "21.11",
        max_jobs: int = 1,
        build_logs: bool = False,
    ) -> List[str]:
        base_names = []
        has_error = False
        build_result_dir = "fb_build_result"
        with self._set_enviromentals(force):
            url = ""
            nix_channel_regepx = re.compile(r"^\d\d\.\d\d(-pre|-beta)?$")
            if repo.lower() == "unstable" or nix_channel_regepx.match(repo.lower()):
                url = "https://github.com/NixOS/nixpkgs/archive/nixos-{}.tar.gz".format(
                    repo
                )
            elif repo.lower() == "master":
                url = "https://github.com/NixOS/nixpkgs/archive/master.tar.gz"
            else:
                url = repo

            nio = NetworkIOHelper()
            nio._download_file_curl(url, "repo.tar.gz")

            if not os.path.isfile("repo.tar.gz"):
                print("Error: can't find downloaded repo file.")
                raise NixBuildError()

            # Extract the tarball to a folder called nix_repo
            if os.path.isdir("nix_repo"):
                shutil.rmtree("nix_repo")
            file = tarfile.open("repo.tar.gz")
            file.extractall("./nix_repo")
            file.close()

            nix_repo_root = ""
            if os.path.exists("./nix_repo/default.nix"):
                nix_repo_root = os.path.dirname("./nix_repo/")
            # Newer versions use the nixos subfolder
            if os.path.exists("./nix_repo/nixos/default.nix"):
                nix_repo_root = os.path.dirname("./nix_repo/nixos/")
            else:
                possible_globs = glob.glob("./nix_repo/*/default.nix", recursive=True)
                if possible_globs:
                    nix_repo_root = os.path.dirname(possible_globs[0])
                else:
                    print("Error: can't determine repo root.")
                    raise NixBuildError()

            patched = self._patch_bootstrap(nix_repo_root)
            if patched:
                print("Bootstrap patch: Success!")
            else:
                print("Bootstrap patch: NO PATCHING HAPPENED! WEIRD!")

            # Now we can build things!
            cmd = []
            cmd.append(self.nix)
            cmd.append("build")
            cmd.append("-f")
            cmd.append(nix_repo_root + "/default.nix")
            cmd.append("-o")
            cmd.append(build_result_dir)
            cmd.append("-j")
            cmd.append(str(max_jobs))
            if build_logs:
                cmd.append("-L")
            cmd.append(pkg_name)
            # Just in case it exists already
            to_delete = glob.glob(f"{build_result_dir}*")
            for entry in to_delete:
                os.unlink(entry)
            print("Running build command:")
            print(" ".join(cmd))
            p = subprocess.Popen(
                cmd,
                bufsize=1,  # Flush on every newline to ensure realtime
                universal_newlines=True,
            )
            p.wait()
            has_error = p.returncode != 0
            if has_error:
                print(f"Error: nix build command exit code: {p.returncode}")
                raise NixBuildError()

            output_dirs = glob.glob(f"{build_result_dir}*")

            if not output_dirs:
                print(f"Error: No build results found: {build_result_dir}*")
                raise NixBuildError()

            for entry in output_dirs:
                resulting_path = os.path.realpath(entry)
                base_name = os.path.basename(resulting_path)
                base_names.append(base_name)

        return base_names

    # Lists paths of all pkgs we should package to RPM based on requested one
    def get_pkgs_to_pack(self, pnames: List[str]) -> List[str]:
        # First, get the path of the requested package
        dirlist = []
        root = Paths.NIX_STORE
        for file in os.listdir(root):
            for pname in pnames:
                if pname in file and os.path.isdir(os.path.join(root, file)):
                    dirlist.append(os.path.join(root, file))
        if len(dirlist) == 0:
            raise NixPackagePathNotFoundError()
        accum = []
        for thisdir in dirlist:
            # Then, shell out to get the path list
            with self._set_enviromentals():
                # all dependencies
                result = subprocess.run(
                    [self.nix_store, "--query", "--requisites", thisdir],
                    capture_output=True,
                )
            accum.extend(result.stdout.decode().split())
        return list(set(accum))  # remove duplicate paths

    # Shell out & get result for nix-store --query --references
    def get_pkgs_references(self, pkg: str) -> List[str]:
        with self._set_enviromentals():
            # immediate dependencies only
            result = subprocess.run(
                [self.nix_store, "--query", "--references", pkg], capture_output=True
            )
        return result.stdout.decode().split()

    # Given a nix package path get the hash and name
    def separate_name_hash(self, path: str) -> Tuple[str, str]:
        matched = re.match(r"^.*/([a-z0-9]{32})-(.*)$", path)
        if not matched:
            raise RuntimeError("Path did not match pattern when trying to separate")
        nixhash = matched.group(1)
        name = matched.group(2)
        return nixhash, name

    def add_cross_compile_pkgs(
        self, pkgs: List, arm: bool = False, x86: bool = False
    ) -> List:
        new_pkgs = []

        # No flags -> just keep the package
        if arm is False and x86 is False:
            return pkgs

        for pkg in pkgs:
            # If it's already a cross compile package,
            # we just take it as is
            if "pkgsCross" in pkg:
                new_pkgs.append(pkg)
            else:
                if Architecture.is_x86():
                    if x86:
                        new_pkgs.append(pkg)
                    if arm:
                        new_pkgs.append(f"pkgsCross.aarch64-darwin.{pkg}")
                if Architecture.is_arm():
                    if arm:
                        new_pkgs.append(pkg)
                    if x86:
                        new_pkgs.append(f"pkgsCross.x86_64-darwin.{pkg}")
        return new_pkgs