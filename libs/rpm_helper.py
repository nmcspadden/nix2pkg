#!/usr/bin/env python3
import os
import shutil
import subprocess
from typing import List, Tuple

from libs.system_helper import Architecture


class RPMHelper:
    # Setting absolute paths for rpmbuild
    topdir = os.path.join(os.getcwd(), "topdir")
    rpmdir = os.path.join(os.getcwd(), "output")
    tmppath = os.path.join(os.getcwd(), "rpm-tmp")

    # Writing spec file lines to file
    def write_lines(self, file_path: str, contents: str) -> None:
        with open(file_path, "w") as f:
            f.write(contents)

    def get_build_arch(self, pkg_name) -> str:
        # Unless we crosscompile, we can pick the native architecture
        # of the machine that compiled the code.
        build_arch = "aarch64" if Architecture.is_arm() else "x86_64"

        # Now to clean up crosscompilation names and set the right arch.
        if "aarch64-apple-darwin-" in pkg_name:
            # 'arm64' is what apple calls uname -m
            # on an apple silicon mac, but aarch64 is what is defined
            # in RPM already.
            build_arch = "aarch64"
        # I assume that's what it will look like if we crosscompile
        # on an arm mac to intel code. Unconfirmed.
        if "x86_64-apple-darwin-" in pkg_name:
            build_arch = "x86_64"
        return build_arch

    # Create a spec file based on some package information
    def generate_spec(
        self,
        pkg_path: str,
        pkg_name: str,
        pkg_hash: str,
        deps_pairs: List[Tuple[str, str]],
    ) -> str:
        # Make the "Requires:..."" line
        req_line = "Requires:"
        nodeps = True
        for dep_hash, dep_name in deps_pairs:
            if dep_hash != pkg_hash:
                req_line = req_line + " " + self._rpm_name(dep_name, dep_hash)
                nodeps = False
        if nodeps:
            req_line = None
        # List of strings representing the spec file
        specfile_contents = [
            "Name: " + self._rpm_name(pkg_name, pkg_hash),
            # Note: sadly we can't specify BuildArch in here
            # We will pass it to the rpmbuild command.
            "Version: 1",
            "Release: 0",
            "Summary: Nix2RPM",
            "Group: Nix2RPM",
            "License: Facebook",
            "AutoReq: No",
            "AutoProv: No",
            "Packager: prod_macos",
            req_line,
            "%description",
            f"Packaged {pkg_name} with hash {pkg_hash} using nix2rpm",
            "%install",
            "mkdir -p $RPM_BUILD_ROOT/opt/facebook/nix/store/",
            f"cp -a {pkg_path} $RPM_BUILD_ROOT/opt/facebook/nix/store/",
            "%files",
            pkg_path,
            "%clean",
            "chmod -R +w $RPM_BUILD_ROOT",
            "rm -rf $RPM_BUILD_ROOT",
        ]
        specfile_contents = list(filter(None, specfile_contents))
        return "\n".join(specfile_contents)

    # Shell out to rpmbuild
    def rpmbuild(self, specfile: str, build_arch: str) -> bool:
        cmd = [
            "rpmbuild",
            "--target",
            build_arch,
            "-bb",
            "--rmspec",
            "--define",
            f"_topdir {self.topdir}",
            "--define",
            f"_rpmdir {self.rpmdir}",
            "--define",
            f"_tmppath {self.tmppath}",
            "--define",
            "_invalid_encoding_terminates_build 0",  # prevent P128054514
            specfile,
        ]
        print(f"Running: {' '.join(cmd)}")
        r = subprocess.run(cmd).returncode
        was_success = r == 0
        return was_success

    # Delete temp files used during the RPM building process
    def cleanup(self) -> None:
        if os.path.exists(self.tmppath):
            shutil.rmtree(self.tmppath)

    # Delete temp files used during the RPM building process
    def clean_output(self) -> None:
        if os.path.exists(self.rpmdir):
            shutil.rmtree(self.rpmdir)

    # Come up with the RPM name based on package name and version/hash
    def _rpm_name(self, pkg_name: str, pkg_hash: str) -> str:
        name = f"nix2rpm-{pkg_name}-{pkg_hash}"
        # sanitization because this symbol will not svnyum publish
        # it causes T71552737 error
        name = name.replace("+", "plus")
        return name
