"""Presenter commands. Run from the demo directory: python -m solace_demo <command>."""

from __future__ import annotations

import argparse
import logging
import platform
import shutil
import sys

from solace_demo import __version__
from solace_demo.agent_mesh import AdvisoryNotConfigured, advisory_summary
from solace_demo.catalog import alert_body, TOPIC_BOTH
from solace_demo.admin_sync import sync_admin_password
from solace_demo.config import ConfigError, config_check_status, load_config, public_report
from solace_demo.provision import provision, recreate_queue, wait_until_ready
from solace_demo.scenarios import Report, architecture_lines, run_access, run_delivery, run_routing
from solace_demo.semp import Semp


def _print_report(report: Report) -> None:
    print(f"== {report.name}: {'PASS' if report.passed else 'FAIL'} ==")
    for line in report.lines:
        print(line)


def _architecture(next_step: str, host: str, vpn: str) -> None:
    print("-- architecture --")
    for line in architecture_lines(host, vpn):
        print(line)
    print(f"Next: {next_step}")


def cmd_prereqs(_args: argparse.Namespace) -> int:
    print(f"solace-ssa-demo {__version__}")
    print(f"python {sys.version.split()[0]} on {platform.system()} {platform.machine()}")
    docker = shutil.which("docker")
    print(f"docker {'found at ' + docker if docker else 'NOT FOUND'}")
    try:
        import solace.messaging  # noqa: F401

        print("solace-pubsubplus import OK")
    except Exception as exc:
        print(f"solace-pubsubplus import FAILED: {exc}")
        print("From demo/, with .venv activated: python -m pip install -r requirements.txt")
        return 1
    print(public_report())
    print("This check does not connect to a broker and does not change one.")
    return 0 if docker else 1


def cmd_config_check(_args: argparse.Namespace) -> int:
    print(public_report())
    print("This check does not connect to a broker and does not change one.")
    return config_check_status()


def cmd_sync_admin_password(_args: argparse.Namespace) -> int:
    config = load_config()
    for line in sync_admin_password(config):
        print(line)
    return 0


def cmd_wait(_args: argparse.Namespace) -> int:
    config = load_config()
    wait_until_ready(config)
    print(f"SEMP ready at loopback Message VPN {config.vpn}")
    return 0


def cmd_provision(_args: argparse.Namespace) -> int:
    config = load_config()
    for line in provision(config):
        print(line)
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    config = load_config()
    recreate_queue(Semp(config), config)
    print("Recreated the demo queue only. Other VPN objects were left in place.")
    return 0


def cmd_routing(_args: argparse.Namespace) -> int:
    config = load_config()
    _architecture("wildcard consumers", config.host, config.vpn)
    report = run_routing(config)
    _print_report(report)
    return 0 if report.passed else 1


def cmd_access(_args: argparse.Namespace) -> int:
    config = load_config()
    _architecture("ACL allow and deny", config.host, config.vpn)
    report = run_access(config)
    _print_report(report)
    return 0 if report.passed else 1


def cmd_delivery(_args: argparse.Namespace) -> int:
    config = load_config()
    _architecture("direct miss versus guaranteed hold, consumer offline, broker path up", config.host, config.vpn)
    report = run_delivery(config)
    _print_report(report)
    return 0 if report.passed else 1


def cmd_quickstart(_args: argparse.Namespace) -> int:
    config = load_config()
    print("Quickstart provisions the local lab, then runs the three core steps.")
    print("Optional Agent Mesh is not called.")
    for line in provision(config):
        print(line)
    failed = False
    steps = (
        ("Step 1 of 3. Return to the architecture, then show topic selection.", run_routing),
        ("Step 2 of 3. Return to the architecture, then show allow and deny.", run_access),
        ("Step 3 of 3. Return to the architecture, then show offline delivery.", run_delivery),
    )
    for reminder, func in steps:
        print()
        _architecture(reminder, config.host, config.vpn)
        report = func(config)
        _print_report(report)
        failed = failed or not report.passed
    print()
    print("Demo recording: none exists.")
    print("Agent Mesh: not run. python -m solace_demo advisory explains why.")
    return 1 if failed else 0


def cmd_web(_args: argparse.Namespace) -> int:
    from solace_demo.web import serve

    serve()
    return 0


def cmd_advisory(_args: argparse.Namespace) -> int:
    sample = alert_body("advisory-not-run-001", TOPIC_BOTH)
    try:
        advisory_summary(sample)
    except AdvisoryNotConfigured as exc:
        print(exc)
        print("Core steps do not need this command.")
        return 2
    print("advisory_summary returned a document. That is a bug: it must refuse.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m solace_demo")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "prereqs": cmd_prereqs,
        "config-check": cmd_config_check,
        "sync-admin-password": cmd_sync_admin_password,
        "wait": cmd_wait,
        "provision": cmd_provision,
        "reset": cmd_reset,
        "routing": cmd_routing,
        "access": cmd_access,
        "delivery": cmd_delivery,
        "quickstart": cmd_quickstart,
        "web": cmd_web,
        "advisory": cmd_advisory,
    }
    for name, func in commands.items():
        command = sub.add_parser(name)
        command.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    for name in ("solace", "solace.messaging", "solace.messaging.receiver"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.ERROR)
        logger.propagate = False
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
