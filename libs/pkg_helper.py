#!/usr/bin/env python3
import os
import shutil
import subprocess
import tempfile
from typing import List


# Process:
# 1) gather all the files we need to package
# 2) generate package name out of each dep
# 3) build each component package
# 4) build dist package from components
class PkgHelper:
    # Create a distribution pkg made up of all components
    def build_dist_pkg(
        self,
        component_packages: List[str],
        pkg_name: str,
        output_dir: str,
    ) -> bool:
        if len(component_packages) == 0:
            print("No component packages to build dist pkg!")
            return False
        cmd = ["/usr/bin/productbuild"]
        for pkg in component_packages:
            cmd.append("--package")
            cmd.append(pkg)
        pkg_name = os.path.join(output_dir, self._dist_pkg_name(pkg_name))
        cmd.append(pkg_name)

        result = subprocess.run(cmd, capture_output=True)
        if not result.returncode == 0:
            print(result.stdout)
            print(result.stderr)
        else:
            print(f"Package found at {pkg_name}")
        return result.returncode == 0

    # Create a component package file, throw error if package did not succeed
    def build_component_pkg(
        self,
        root_dir: str,
        identifier: str,
        version: str,
        pkg_name: str,
        pkg_hash: str,
        output_dir: str,
    ) -> bool:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmproot:
            # Copy actual root into tmproot
            fixed_root = os.path.join(tmproot, root_dir.lstrip("/"))
            # print(f"Copying {root_dir} into {tmproot}")
            shutil.copytree(root_dir, fixed_root, symlinks=True, ignore_dangling_symlinks=True, dirs_exist_ok=True)
            cmd = [
                "/usr/bin/pkgbuild",
                "--root",
                tmproot,
                "--identifier",
                identifier,
                "--version",
                version,
                os.path.join(output_dir, self._comp_pkg_name(pkg_name, pkg_hash)),
            ]
            # print("pkgbuild command: ")
            # print(" ".join(cmd))
            # print("Running pkgbuild command")
            result = subprocess.run(cmd, capture_output=True)
        if not result.returncode == 0:
            print(result.stdout)
            print(result.stderr)
        return result.returncode == 0

    # Generate component package name based on package name and version/hash
    def _comp_pkg_name(self, pkg_name: str, pkg_hash: str) -> str:
        name = f"{pkg_name}-{pkg_hash}.pkg"
        # sanitization because this symbol causes errors with some web hosts
        name = name.replace("+", "plus")
        return name

    # Generate dist package name
    def _dist_pkg_name(self, pkg_name: str) -> str:
        name = f"nix2pkg-{pkg_name}.pkg"
        # sanitization because this symbol causes errors with some web hosts
        name = name.replace("+", "plus")
        return name
