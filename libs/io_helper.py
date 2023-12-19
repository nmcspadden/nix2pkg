#!/usr/bin/env python3
import glob
import os
import pathlib
import shutil
import subprocess
import tarfile
from typing import Optional

from libs.system_helper import Architecture


class Paths:
    # These paths are hardcoded - you will need to adjust these for what version of nix you have installed
    # Some day, I'll figure out how to determine these paths programatically
    if Architecture.is_x86():
        # X86
        # These are out of date
        nix_path = "68mfbnrkd4kghrai35f9rz6hn737fn98-nix-2.3.14pre7112_bd4e03d"
        nss_path = "8k0nxlkbmw6am0mn5xm5j7p0ir1z5g65-nss-cacert-3.66"
    else:
        # ARM
        nix_path = "53r8ay20mygy2sifn7j2p8wjqlx2kxik-nix-2.19.2"
        nss_path = "8ma7xas2nb0i3lq8mm7fpgalv94s8pzh-nss-cacert-3.92"

    # /nix is the default path; change this to match whatever you install with
    NIX_INSTALL = "/nix"
    NIX_STORE = os.path.join(NIX_INSTALL, "store")
    NIX_PACKAGE = os.path.join(NIX_STORE, nix_path)
    NIX_BIN = os.path.join(NIX_PACKAGE, "bin")
    CA_PACKAGE = os.path.join(NIX_STORE, nss_path)
    NIX_VAR = os.path.join(NIX_INSTALL, "var")
    NIX_PROFILES = os.path.join(NIX_VAR, "nix/profiles")
    NIX_STATE = os.path.join(NIX_VAR, "nix")
    NIX_LOG = os.path.join(NIX_VAR, "log/nix")
    NIX_CONFIG = os.path.join(NIX_INSTALL, "conf")
    CONFIG_FILE = os.path.join(NIX_CONFIG, "nix/nix.conf")
    PACKAGES_OUT = os.path.join(
        pathlib.Path(__file__).parent.parent.resolve(), "packages"
    )


class WrongArchiveType(Exception):
    pass


class LocalIOHelper:
    # Untar and return extracted dir name
    def untar_archive(self, archivepath: str) -> str:
        expect_extension = ".tar.xz"
        if not archivepath.endswith(expect_extension):
            raise WrongArchiveType()
        extracted_name = os.path.basename(archivepath).replace(expect_extension, "")
        # Delete any previous extracted dir
        if os.path.isdir(extracted_name):
            shutil.rmtree(extracted_name)
        tar = tarfile.open(archivepath)
        tar.extractall()
        tar.close
        return extracted_name

    # From the extracted dir, move out the files to the right place
    def install_files(self, extracteddir: str) -> None:
        # Symlink is assumed to be present
        if not os.path.isdir(Paths.NIX_INSTALL):
            raise RuntimeError("Nix directory missing on system")
        # Fix run as root via setting a config
        os.makedirs(os.path.dirname(Paths.CONFIG_FILE), exist_ok=True)
        with open(Paths.CONFIG_FILE, "w") as confile:
            confile.write("build-users-group =")

        try:
            os.mkdir(Paths.NIX_STORE)
            print("The store directory did not previously exist")
        except FileExistsError:
            print("The store directory already exists")

        # Move over the packages
        fresh = os.path.join(extracteddir, "store")
        for pkg in os.listdir(fresh):
            if os.path.exists(os.path.join(Paths.NIX_STORE, pkg)):
                print("Already exists: " + str(pkg))
            else:
                shutil.move(os.path.join(fresh, pkg), Paths.NIX_STORE)

        # Following officlial installer which does chmod -R a-w
        # /nix/store should be writable because we want to add new stuff
        # /nix/store/* should be recursivly unwritable. Packages never modified
        for item in glob.glob(os.path.join(Paths.NIX_STORE, "*")):
            subprocess.run(["chmod", "-R", "555", item], stderr=subprocess.DEVNULL)

    # Remove all nix2rpm files
    def removal(self) -> None:
        # remove .nix* files in ~
        print("Removing Nix files in home directory")
        channels = os.path.expanduser("~/.nix-channels")
        profile = os.path.expanduser("~/.nix-profile")
        defe = os.path.expanduser("~/.nix-defexpr")
        if os.path.exists(channels):
            os.remove(channels)
        if os.path.islink(profile):
            os.unlink(profile)
        if os.path.isdir(defe):
            shutil.rmtree(defe)

        print("Removing var directory if exists")
        if os.path.exists(Paths.NIX_VAR):
            shutil.rmtree(Paths.NIX_VAR)

        print("Removing config directory if exists")
        if os.path.exists(Paths.NIX_CONFIG):
            shutil.rmtree(Paths.NIX_CONFIG)

        # Remove store packages that we have permission to remove
        print("Removing installed packages")
        for item in glob.glob(os.path.join(Paths.NIX_STORE, "*")):
            subprocess.run(["chmod", "-R", "+w", item], stderr=subprocess.DEVNULL)
            subprocess.run(["rm", "-rf", item], stderr=subprocess.DEVNULL)

    # Remove the downloaded files used for installation
    def clean_install_files(self, archivename: str) -> None:
        dirname = archivename.replace(".tar.xz", "")
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        if os.path.exists(archivename):
            os.remove(archivename)

    # Give the packages in store the correct permissions since it goes into the RPM
    def own_store(self, user: str = "root") -> int:
        # Assumes we have permission via sudoers file to do this
        r = subprocess.run(
            ["sudo", "chown", "-H", "-R", user + ":wheel", Paths.NIX_STORE], timeout=300
        ).returncode
        return r


class NetworkIOHelper:
    release_url_x86 = (
        "replace me"
    )

    release_url_arm = (
        "replace me"
    )

    # Download archive returning its name
    def download_release(self, public=True) -> str:
        # TODO: Replace this with DeterminateSystems installer pkg
        # if Architecture.is_x86():
        #     return self._download_file_curl(self.release_url_x86)
        # else:
        #     return self._download_file_curl(self.release_url_arm)
        return

    # Download file in curl subprocess
    def _download_file_curl(
        self, target_url: str, file_name: Optional[str] = None
    ) -> str:
        target = file_name if file_name else os.path.basename(target_url)
        c = f'/usr/bin/curl -L "{target_url}" -o "{target}" '
        subprocess.run([c], shell=True, stdout=subprocess.DEVNULL)
        return target
