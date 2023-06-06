#!/usr/bin/env python3
"""Script to publish docker images and manifests."""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from os import getenv

ARCH_386 = "i386"
ARCH_AMD64 = "amd64"
ARCH_ARMV6 = "armv6"
ARCH_ARMV7 = "armv7"
ARCH_ARM64 = "aarch64"
ARCHS = [ARCH_386, ARCH_AMD64, ARCH_ARMV6, ARCH_ARMV7, ARCH_ARM64]

PUBLISH_LATEST = "{repo}:{arch}-latest"

PUBLISH_NAMES = [
    "{repo}:{arch}{run_number}",
    "{repo}:{arch}-{base_tag}",
    "{repo}:{arch}-{base_tag}{run_number}",
    "{repo}:{arch}-{base_tag}{github_sha}",
]

MANIFEST_NAMES = [
    "{repo}:{run_number}",
    "{repo}:{base_tag}",
    "{repo}:{base_tag}{run_number}",
    "{repo}:{base_tag}{github_sha}",
]

parser = argparse.ArgumentParser()
parser.add_argument("--tag", type=str, required=True, help="Base tag to publish")
parser.add_argument(
    "--repo",
    type=str,
    required=True,
    help="Repo to publish to (includes registry if not Docker Hub)",
)
parser.add_argument(
    "--latest", required=False, action="store_true", help="Publish latest tag"
)
parser.add_argument(
    "--dry-run",
    required=False,
    action="store_true",
    help="Print commands only",
)
parser.add_argument("--ci", required=False, action="store_true", help="Running in CI")
parser.add_argument(
    "--run-number",
    type=str,
    required=False,
    default="",
    help="Run number to append to tags if ci is not specified",
)
parser.add_argument(
    "--github-sha",
    type=str,
    required=False,
    default="",
    help="GitHub SHA to append to tags if ci is not specified",
)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
    "--image", action="store_true", help="Publish architecture image to all tags"
)
group.add_argument(
    "--manifest",
    action="store_true",
    help="Publish manifest to all tags",
)
opts, _ = parser.parse_known_args()
if opts.image:
    parser.add_argument(
        "--arch",
        type=str,
        required=True,
        help="Architecture to publish",
        choices=ARCHS,
    )
    parser.add_argument(
        "--image-name",
        type=str,
        required=True,
        help="Name of image to publish",
    )


@dataclass(frozen=True)
class DockerNames:
    """Preformatted docker image names."""

    ci_name: str | None
    names: list

    manifests: list
    manifest_base: str | None
    manifest_cmd_base: list | None

    # Remove duplicates caused by empty run_number or github_sha
    # Cleans docker command
    @staticmethod
    def _clean_list(duplicates: list) -> list:
        cleaned = [x.replace(":-", ":") for x in duplicates if not x.endswith(":")]
        cleaned = list(set(cleaned))
        return cleaned

    @classmethod
    def from_args(cls, args):
        """Create names from args."""
        if args.ci:
            run_number = getenv("GITHUB_RUN_NUMBER")
            github_sha = getenv("GITHUB_SHA")
        else:
            run_number = args.run_number if args.run_number else ""
            github_sha = args.github_sha if args.github_sha else ""
        run_number = f"-{run_number}"
        github_sha = f"-{github_sha}"

        if not args.image:
            preformatted_names = []
            ci_name = None
        else:
            preformatted_names = [
                publish_name.format(
                    repo=args.repo,
                    arch=args.arch,
                    base_tag=args.tag,
                    run_number=run_number,
                    github_sha=github_sha,
                )
                for publish_name in PUBLISH_NAMES
            ]
            if args.latest:
                preformatted_names.append(
                    PUBLISH_LATEST.format(repo=args.repo, arch=args.arch)
                )
            preformatted_names = cls._clean_list(preformatted_names)
            ci_name = args.image_name

        if not args.manifest:
            preformatted_manifests = []
            manifest_base = None
            manifest_cmd_base = None
        else:
            preformatted_manifests = [
                manifest_name.format(
                    repo=args.repo,
                    arch="{arch}",
                    base_tag=args.tag,
                    run_number=run_number,
                    github_sha=github_sha,
                )
                for manifest_name in MANIFEST_NAMES
            ]
            if args.latest:
                preformatted_manifests.append(f"{args.repo}:latest")
            preformatted_manifests = cls._clean_list(preformatted_manifests)
            manifest_base = PUBLISH_NAMES[0].format(
                repo=args.repo,
                arch="{arch}",
                base_tag=args.tag,
                run_number=run_number,
                github_sha=github_sha,
            )

            manifest_cmd_base = [manifest_base.format(arch=arch) for arch in ARCHS]

        return cls(
            names=preformatted_names,
            manifests=preformatted_manifests,
            ci_name=ci_name,
            manifest_base=manifest_base,
            manifest_cmd_base=manifest_cmd_base,
        )


def main():
    """Run main script."""
    args = parser.parse_args()
    docker_names = DockerNames.from_args(args)

    def run_command(*command, ignore_error: bool = False):
        """Run command and print output."""
        print(f"$ {shlex.join(list(command))}")
        if not args.dry_run:
            rc = subprocess.call(list(command))
            if rc != 0 and not ignore_error:
                print("Command failed")
                sys.exit(1)

    for name in docker_names.names:
        cmd = [
            "docker",
            "tag",
            docker_names.ci_name,
            name,
        ]
        run_command(*cmd)
        cmd = ["docker", "push", name]
        run_command(*cmd)
        print(f"Published {name}")

    for manifest in docker_names.manifests:
        cmd = [
            "docker",
            "manifest",
            "create",
            manifest,
            *docker_names.manifest_cmd_base,
        ]
        run_command(*cmd)

        cmd = ["docker", "manifest", "push", manifest]
        run_command(*cmd)
        print(f"Published {manifest}")


if __name__ == "__main__":
    main()
