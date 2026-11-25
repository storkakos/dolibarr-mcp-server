"""TEST ONLY. End to end: the check lists of the test stack against the stack, through the proxy. Each check
is reported as PASS, FAIL or SKIP; exit code 1 if any check failed.

The checks live in check groups, one file per group in groups/ (see checklib.py and README.md), run in
this order:
    oauth      the OAuth flow through restoauth and its negative cases
    rights     a user without the connect right, two connected users with different rights
    ends       how a connection ends: user disabled, ended on the user card, access token expired
    librechat  the example setup with LibreChat (docs/setup/example-keycloak-librechat.md, checks 5 to 8)
    proxy      the reverse proxy: restoauth discovery, the MCP server under a path prefix (nginx)

    docker compose run --rm client                                        # every group
    docker compose run --rm client python checks.py oauth rights          # only these groups
    docker compose run --rm client python checks.py --list                # the groups and their checks
    docker compose run --rm --no-deps client python checks.py --services oauth
        # prints the compose services to start for these groups (here: setup), for "up -d"

Later checks use what earlier ones set up (tokens, record ids); after a failure they fail too. A group
that builds on another one (Group.needs, e.g. rights on oauth) brings it along when it runs alone.
-v prints the traceback of a failed check. Exit code 2: an unknown group name.
"""
import argparse
import importlib
import pkgutil
import sys

import groups

# Every run needs the one-shot setup and what it depends on (proxy, Dolibarr, Keycloak, MCP server).
BASE_SERVICES = ["setup"]


def all_groups() -> list:
    found = [importlib.import_module(f"groups.{m.name}").group for m in pkgutil.iter_modules(groups.__path__)]
    return sorted(found, key=lambda g: g.order)


def main() -> int:
    p = argparse.ArgumentParser(description="Check lists of the test stack.")
    p.add_argument("groups", nargs="*", metavar="GROUP", help="groups to run (default: all)")
    p.add_argument("-v", action="store_true", help="traceback of a failed check")
    p.add_argument("--list", action="store_true", help="list the groups and their checks")
    p.add_argument("--services", action="store_true", help="print the compose services the groups need")
    a = p.parse_args()

    known = all_groups()
    by_name = {g.name: g for g in known}
    wanted = [x for arg in a.groups for x in arg.replace(",", " ").split()]
    if not wanted or "all" in wanted:
        wanted = list(by_name)
    unknown = [x for x in wanted if x not in by_name]
    if unknown:
        print(f"unknown check group: {' '.join(unknown)} (groups: {' '.join(by_name)}, or all)", file=sys.stderr)
        return 2
    # The groups a chosen group builds on run too (before it, by their order).
    added, todo = [], list(wanted)
    while todo:
        for need in by_name[todo.pop()].needs:
            if need not in wanted and need not in added:
                added.append(need)
                todo.append(need)
    chosen = [g for g in known if g.name in wanted or g.name in added]

    if a.services:
        services = list(BASE_SERVICES)
        for g in chosen:
            services += [s for s in g.services if s not in services]
        print(" ".join(services))
        return 0
    if a.list:
        for g in chosen:
            extra = [f"needs {' '.join(g.services)}"] if g.services else []
            extra += [f"builds on {' '.join(g.needs)}"] if g.needs else []
            print(f"{g.name}: {g.title} ({', '.join([f'{len(g.checks)} checks'] + extra)})")
            for name, _ in g.checks:
                print(f"    {name}")
        return 0

    if added:
        print(f"also running {' '.join(added)}: the chosen groups build on it", flush=True)
    results: list = []
    for g in chosen:
        g.run(results)
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r[0] == 'SKIP' for r in results)} skipped"
          + ("" if len(chosen) == len(known) else f" (groups: {' '.join(g.name for g in chosen)})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
