# nix2pkg
 
Builds an RPM or Apple package from a Nix expression.

## Usage
First, you will need to install nix on macOS: 
https://determinate.systems/posts/graphical-nix-installer

This script currently assumes you are using the default mountpoint of `/nix`. If not, change line 27 in io_helper.py to reflect the correct nix volume/folder.

To run this script, invoke it with the nix package you want to install:
```
./main.py package <package name> --pkg
```

If `--pkg` is specified, you will get an Apple package. Otherwise, it will attempt to build an RPM (and fail if you don't have `rpmbuild` installed).

The package must be found in the official Nix pkgs repository:
https://github.com/NixOS/nixpkgs

### EXAMPLE:
Creating an Apple package for `jq`:
```
% ./main.py package jq --pkg
Starting to package: ['jq']
Cleaning up RPM 'output' directory.
Building: jq
Using repo: 21.11
Building phase started
Downloading nixpkgs tarball from Github
Extracting downloaded tarball
Configuring repo root
Patch bootstrap script
Patching unpack-bootstrap-tools.sh
Bootstrap patch: NO PATCHING HAPPENED! WEIRD!
Building package
Running build command:
/nix/store/53r8ay20mygy2sifn7j2p8wjqlx2kxik-nix-2.19.2/bin/nix --extra-experimental-features nix-command build -f ./nix_repo/nixpkgs-nixos-21.11/default.nix -o build_result -j 8 jq
Build phase done: jq
Creating component package for jq-1.6-bin
Creating component package for jq-1.6-lib
Creating component package for jq-1.6-man
Creating component package for libobjc-11.0.0
Creating component package for apple-framework-CoreFoundation-11.0.0
Creating component package for onig-6.9.7.1
Creating component package for bash-5.1-p8
Building distribution package
Package found at /Users/nmcspadden/Documents/GitHub/nix2pkg/packages/nix2pkg-jq-1.6-bin-jggfg8i9y76kpp10nhbj150zvz24qqz9.pkg
Finished packinging successfully. Cleaning up.
```

## RPM Builds

The open source version of this is untested, but if you have `rpmbuild` installed, it should work.

## Pkg Builds

For a given nix package, it will build a component package out of each dependency, and store them in the "packages" directory. At the end, it will build a Distribution style package prefixed with `nix2pkg-` and store it in the "packages" directory.

This Distribution package contains all of the component packages, and theoretically anything you need to install a working copy of the package on a Mac. As currently implemented, it only installs in the default path of `/nix`. A future version will allow relocating this to wherever path makes sense.

