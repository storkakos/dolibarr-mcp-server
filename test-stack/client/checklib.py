"""TEST ONLY. The building blocks of a check group (see groups/ and checks.py).

A group is one file groups/<name>.py; the file name is the group name. The file creates one Group and
marks its checks with @group.check("..."). checks.py finds every group file, so adding a check or a
group touches no other group's file and not checks.py.

Later checks use what earlier ones set up (tokens, record ids): they share the dict `state`. A group
that builds on another group's state names it in `needs`; checks.py then runs that group first, also
when only the later group was asked for.
"""
import sys
import traceback

# What the checks of one run hand on to later checks, also across groups (see Group.needs).
state: dict = {}


class Skip(Exception):
    """Raised by a check (or a flow it calls) that cannot run for a reason outside the code under test,
    e.g. LibreChat's login limit. The check reports SKIP with the message instead of FAIL."""


class Group:
    def __init__(self, module: str, title: str, order: int, services: tuple = (), ready=None,
                 needs: tuple = ()):
        """module: the group file's __name__ (its last part is the group name).
        title: the heading printed before the group's checks.
        order: groups run in ascending order, whatever order they are named in.
        services: compose services the group needs on top of the setup and its dependencies
            (e.g. "librechat"). A run of groups without any starts only the setup's part of the stack.
        ready: called once before the group's first check, to wait until its services answer. If it
            raises, every check of the group fails with that message and is not run.
        needs: names of the groups whose state this group uses; they run before it in every run."""
        self.name = module.rsplit(".", 1)[-1]
        self.title, self.order, self.services, self.ready = title, order, tuple(services), ready
        self.needs = tuple(needs)
        self.checks: list = []

    def check(self, name: str):
        def deco(fn):
            self.checks.append((name, fn))
            return fn
        return deco

    def run(self, results: list) -> None:
        print(f"== {self.title}", flush=True)
        not_ready = None
        if self.ready:
            try:
                self.ready()
            except Exception as e:  # noqa: BLE001
                not_ready = f"not run: {e}"
        for name, fn in self.checks:
            if not_ready:
                results.append(("FAIL", name, not_ready))
            else:
                try:
                    detail = fn()
                    if isinstance(detail, str) and detail.startswith("SKIP"):
                        results.append(("SKIP", name, detail[5:]))
                    else:
                        results.append(("PASS", name, detail or ""))
                except Skip as e:
                    results.append(("SKIP", name, str(e)))
                except Exception as e:  # noqa: BLE001
                    results.append(("FAIL", name, f"{type(e).__name__}: {e}"))
                    if "-v" in sys.argv:
                        traceback.print_exc()
            status, _, detail = results[-1]
            print(f"{status}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
