#!/usr/bin/env python3

import os
import traceback

import click
from libs.io_helper import LocalIOHelper, NetworkIOHelper
from libs.nix_helper import NixBuildError, NixHelper
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
def package(
    repo, force, pkgs, arm: bool, x86: bool, max_jobs: int, build_logs: bool
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
    io = LocalIOHelper()
    if not nix.is_installed():
        click.echo("nix2pkg needs to be prepared")
        exit(1)
    try:
        pkgs = nix.add_cross_compile_pkgs(pkgs, arm, x86)
        print(pkgs)
        click.echo(f"Starting to package: {str(pkgs)}")
        rpm_error = False
        # click.echo("Owning store as facebook.")
        # io.own_store("facebook")
        # Clean the rpm output folder so
        # we don't have old stuff in there
        click.echo("Cleaning up 'output' directory.")
        rpm.clean_output()
        for pkg in pkgs:
            # If a previous rpm failed to package,
            # let's stop building stuff
            if rpm_error:
                break
            click.echo(f"Bulding: {pkg}")
            click.echo(f"Using repo: {repo}")
            nix.switch_profile(pkg)
            base_names = nix.build_pkg(pkg, force, repo, max_jobs, build_logs)
            click.echo(f"Build phase done: {pkg}")
            click.echo(f"Preparing to package: {base_names}")
            all_pkgs = nix.get_pkgs_to_pack(base_names)
            for pkg_path in all_pkgs:
                pkg_hash, pkg_name = nix.separate_name_hash(pkg_path)
                click.echo(f"Packaging: {pkg_name}")
                deps = nix.get_pkgs_references(pkg_path)
                deps_pairs = [nix.separate_name_hash(p) for p in deps]
                spec_name = f"{pkg_name}-{pkg_hash}.spec"
                spec_contents = rpm.generate_spec(
                    pkg_path, pkg_name, pkg_hash, deps_pairs
                )
                rpm.write_lines(spec_name, spec_contents)
                build_arch = rpm.get_build_arch(pkg_name)
                click.echo(f"Normally, this is where we would build the RPM: {build_arch}")
                success = True
                # success = rpm.rpmbuild(spec_name, build_arch)
                if not success:
                    rpm_error = True
                    click.echo(f"RPM packaging error: {spec_name}")
                    break
        exit_code = 0
        if rpm_error:
            click.echo("There were errors during packaging. Cleaning up.")
            exit_code = 1
        else:
            click.echo("Finished packinging successfully. Cleaning up.")
        click.echo("Owning store as root.")
        io.own_store("root")
        click.echo("Deleting temporary rpm files.")
        rpm.cleanup()
        exit(exit_code)
    except NixBuildError:
        click.echo("\nPackage could not be built. Packaging stopped.")
        click.echo("Owning store back to root.")
        io.own_store("root")
        exit(1)


cli.add_command(prepare)
cli.add_command(destroy)
cli.add_command(package)

if __name__ == "__main__":
    cli()
