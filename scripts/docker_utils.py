"""Docker Compose helpers shared by local operational checks."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def add_compose_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--project-name")
    parser.add_argument("--compose-file", action="append", default=[])
    parser.add_argument("--env-file")


def compose_from_args(args):
    command = ["docker", "compose"]
    if args.project_name:
        command += ["--project-name", args.project_name]
    for filename in args.compose_file:
        command += ["--file", str((ROOT / filename).resolve())]
    if args.env_file:
        command += ["--env-file", str((ROOT / args.env_file).resolve())]
    return command


def run_compose(command, *arguments, **kwargs):
    return subprocess.run(command + list(arguments), cwd=ROOT, check=True, **kwargs)
