#!/usr/bin/env python3

import glob
import os
import traceback

import click

from libs.io_helper import LocalIOHelper, NetworkIOHelper, Paths
from libs.nix_helper import NixBuildError, NixHelper
from libs.pkg_helper import PkgHelper
from libs.rpm_helper import RPMHelper


@click.group(epilog="Example: get ffmpeg RPMs: nix2pkg prepare, nix2pkg package ffmpeg")
def cli() -> None:
    """nix2pkg is a tool for creating RPMs for macOS. It uses Nix package manager."""
    pass


@click.command()
def prepare() -> None:
    """Installs Nix package manager to the system as first time setup.
    Installs Nix to /opt/facebook/nix and adds config files in the home directory."""
    net = NetworkIOHelper()
    fs = LocalIOHelper()
    nix = NixHelper()
    if not nix.is_installed():
        click.echo("Nix is not installed, doing the FB-style install which will fail")
        click.echo("Downloading archive.")
        archive = net.download_release()
        try:
            click.echo("Verifying hash.")
            click.echo("Extracting archive.")
            extracted = fs.untar_archive(archive)
            click.echo("Installing files.")
            fs.install_files(extracted)
            click.echo("Setting up Nix.")
            nix.initial_setup(extracted)
            click.echo("Finished install.")
        except Exception as e:
            click.echo("Error\n" + str(e))
            if click.confirm("Details?"):
                traceback.print_exc()
        finally:
            click.echo("Cleaning leftover files")
            fs.clean_install_files(archive)
    else:
        click.echo("nix2pkg is already prepared.")


@click.command()
def destroy() -> None:
    """Removes the Nix package manager from the system.
    It is not necessary to run this.
    All Nix packages including those installed via RPM
    are removed."""
    click.echo("Removing nix2pkg.")
    click.echo("Normally we'd call fs.removal() here, but commented out")
    # fs = LocalIOHelper()
    # fs.removal()
    click.echo("Finished removal.")


@click.command()
@click.argument("pkgs", nargs=-1)
@click.option(
    "--force",
    default=False,
    is_flag=True,
    help="Attempt to build broken/unsupported packages.",
)
@click.option(
    "--repo",
    show_default=True,
    type=str,
    default="21.11",
    help="Attempt to build from 'unstable', 'master', '21.11', or URL of a tarball containing nix expressions",
)
@click.option(
    "--arm",
    default=False,
    is_flag=True,
    help="To build an ARM package.",
)
@click.option(
    "--x86",
    default=False,
    is_flag=True,
    help="To build an x86 package.",
)
@click.option(
    "--max-jobs",
    default=os.cpu_count(),
    type=click.IntRange(1, os.cpu_count(), clamp=True),
    help="Specify maximum number of jobs to run.",
)
@click.option(
    "--build-logs",
    default=False,
    is_flag=True,
    help="Print full build logs.",
)
@click.option(
    "--pkg",
    default=False,
    is_flag=True,
    help="Create an Apple distribution pkg instead of an RPM.",
)
def package(
    force, repo, pkgs, arm: bool, x86: bool, max_jobs: int, build_logs: bool, pkg: bool
) -> None:
    """Installs the specified package and create pkgs for
    it and its dependencies.
    Running 'install' first is NOT required.
    PKGs will be in a directory called 'output/'.
    Optionally, append -<version> to the package name
    to specify a specific version. Example:
    nix2pkg package wget OR nix2pkg package wget-1.20.3"""
    pkgs = list(pkgs)
    nix = NixHelper()
    rpm = RPMHelper()
    pkgh = PkgHelper()
    io = LocalIOHelper()
    nix_paths = Paths()
    pkg_error = False
    if not nix.is_installed():
        click.echo("nix2pkg needs to be prepared")
        exit(1)
    try:
        pkgs = nix.add_cross_compile_pkgs(pkgs, arm, x86)
        click.echo(f"Starting to package: {str(pkgs)}")
        rpm_error = False
        # click.echo("Owning store as facebook.")
        # io.own_store("facebook")
        # Clean the rpm output folder so
        # we don't have old stuff in there
        click.echo("Cleaning up RPM 'output' directory.")
        rpm.clean_output()
        for package in pkgs:
            # If a previous rpm failed to package,
            # let's stop building stuff
            if rpm_error:
                break
            click.echo(f"Building: {package}")
            click.echo(f"Using repo: {repo}")
            nix.switch_profile(package)
            click.echo("Building phase started")
            base_names = nix.build_pkg(package, force, repo, max_jobs, build_logs)
            click.echo(f"Build phase done: {package}")
            # click.echo(f"Preparing to package: {base_names}")
            all_pkgs = nix.get_pkgs_to_pack(base_names)
            # click.echo(f"Packages to pack: {all_pkgs}")
            # Make a new temp dir
            packages_dir = os.path.join(os.curdir, "packages")
            os.makedirs(packages_dir, exist_ok=True)
            os.chdir(packages_dir)
            for pkg_path in all_pkgs:
                pkg_hash, pkg_name = nix.separate_name_hash(pkg_path)
                click.echo(f"Packaging: {pkg_name}")
                deps = nix.get_pkgs_references(pkg_path)
                deps_pairs = [nix.separate_name_hash(p) for p in deps]
                # click.echo(f"Dependencies: {deps_pairs}")
                if pkg:
                    # print(f"Package path: {pkg_path}")
                    if not os.path.isdir(pkg_path):
                        continue
                    success: bool = create_cpkg(
                        nix_paths,
                        pkgh,
                        pkg_path,
                        pkg_name,
                        pkg_hash,
                    )
                else:
                    success: bool = create_rpm(
                        rpm, pkg_path, pkg_name, pkg_hash, deps_pairs
                    )
                if not success:
                    pkg_error = True
                    click.echo(f"Packaging error: {pkg_path}")
                    break
        if pkg:
            click.echo("Building distribution package")
            # We take the first package from the list to use as our primary
            pkg_hash, pkg_name = nix.separate_name_hash(all_pkgs[0])
            success: bool = create_dpkg(nix_paths, pkgh, pkg_name, pkg_hash)
            if not success:
                pkg_error = True
                click.echo("Packaging error during distribution build")

        exit_code = 0
        if pkg_error:
            click.echo("There were errors during packaging. Cleaning up.")
            exit_code = 1
        else:
            click.echo("Finished packinging successfully. Cleaning up.")
        # click.echo("Owning store as root.")
        # io.own_store("root")
        # click.echo("Deleting temporary rpm files.")
        # rpm.cleanup()
        exit(exit_code)
    except NixBuildError:
        click.echo("\nPackage could not be built. Packaging stopped.")
        # click.echo("Owning store back to root.")
        # io.own_store("root")
        exit(1)


# Create the RPM
def create_rpm(rpm: RPMHelper, pkg_path, pkg_name, pkg_hash, deps_pairs) -> bool:
    print("Creating RPM")
    spec_name = f"{pkg_name}-{pkg_hash}.spec"
    spec_contents = rpm.generate_spec(pkg_path, pkg_name, pkg_hash, deps_pairs)
    rpm.write_lines(spec_name, spec_contents)
    build_arch = rpm.get_build_arch(pkg_name)
    success = rpm.rpmbuild(spec_name, build_arch)
    return success


# Create the component Apple packages
def create_cpkg(nix_paths: Paths, pkg: PkgHelper, pkg_path, pkg_name, pkg_hash) -> bool:
    print(f"Creating component package for {pkg_name}")
    # Create the component packages
    identifier = f"com.meta.nix2pkg.{pkg_hash}-{pkg_name}"
    version = "1.0"
    success = pkg.build_component_pkg(
        pkg_path, identifier, version, pkg_name, pkg_hash, nix_paths.PACKAGES_OUT
    )
    return success


# Create the distribution Apple package out of the components
def create_dpkg(nix_paths: Paths, pkgh: PkgHelper, pkg_name, pkg_hash) -> bool:
    # Assume all the component package are in the "./packages" folder
    # print("Creating distribution package")
    components = glob.glob(os.path.join(nix_paths.PACKAGES_OUT, "*.pkg"))
    success = pkgh.build_dist_pkg(
        components, pkg_name, pkg_hash, nix_paths.PACKAGES_OUT
    )
    return success


cli.add_command(prepare)
cli.add_command(destroy)
cli.add_command(package)

if __name__ == "__main__":
    cli()
