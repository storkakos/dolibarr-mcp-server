# Test VM (Docker host)

A throwaway VM on the maintainer's LAN for running the tests and anything that needs Docker. This dev machine has neither Docker nor WSL. The VM is shared with `itop-mcp-server`, which is why its SSH key carries that name.

| | |
| --- | --- |
| Host | `192.168.178.25` (only reachable from the maintainer's network) |
| User | `root` |
| OS | Debian 13 (trixie), Docker 29.10, Compose v5.8, 4 CPUs, 12 GB RAM minimum with ballooning (15.5 GB visible on 2026-11-25; the visible amount changes), no swap, 59 GB root disk (about 20 GB used) |
| Private key | `~/.ssh/itop-mcp-test-vm` (on the maintainer's machine, **never commit it**) |
| Host key | `~/.ssh/itop-mcp-test-vm.known_hosts` |

No password is written down anywhere. If the key is missing or rejected, ask the maintainer. Don't try to guess or recover a password.

## Only `vm-runner` uses the VM

When several agents work at once, exactly one session, the pane **`vm-runner`**, talks to the VM. **Ticket agents never run `ssh`, `scripts/test-on-vm.sh` or `scripts/stack-on-vm.sh` themselves**, not even to look. They commit, queue a request and wait for the result file. Each agent starting its own stacks made runs slow and fought over the VM's RAM; one runner with a queue does not.

The queue is the folder `.vm-queue/` in the workspace, next to the repos: `../.vm-queue/` from the main checkout's root. From a worktree, go through the main checkout (see [issue-tracker.md](issue-tracker.md#where-scratch-lives)):

```sh
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
QUEUE="$MAIN/../.vm-queue"
cat "$QUEUE/README.md"
```

**`../.vm-queue/README.md` is the single source of the protocol.** Read it before you queue; if this summary and the README ever disagree, the README wins. In short:

- **Request** `<agent>.md`, written only after the commit: `agent`, `repo`, `branch`, `commit`, `target` (the branch you will be merged into), `kind` (`batch` or `single`), `needs` (`stack`, `pytest`, `lint`, `stack+pytest`), `variant` (`caddy`, `nginx`, `both`), `checks` (check groups or `all`), `pytest` (paths or `all`), `llm` (`key`, `none`, `both`) and `proves` (which criteria the run proves). One request per agent; to re-queue, overwrite it with the new commit and delete your old result.
- **`batch`** (default): the runner may merge your branch with other queued branches of the same repo into a temporary integration branch (from `target`) and test them all in one stack with only the check groups the requests need. **`single`**: a run that cannot be shared (a deliberately failing check, Ctrl-C, a scenario step by step); you give the exact `## Steps` and, for temporary changes, a `## Patch`, never a commit.
- **Result** `<agent>.result.md`, written only by `vm-runner`: `commit`, `status` (`PASS`, `FAIL`, `CONFLICT`, `ERROR`), `run` (the RUN name and what it included), `summary` and an excerpt. What to do with each status is in [issue-tracker.md](issue-tracker.md#testing-through-the-vm-queue).
- **Finding the culprit**: when a batch run fails, the runner reruns the failing check group (or test) per branch. The branch that fails alone gets `FAIL` with its lines; the others get `PASS`. A branch that does not merge cleanly gets `CONFLICT` and is run alone or sent back for a rebase.

### What the runner takes care of

These are `vm-runner`'s job, not the ticket agent's:

- the VM rules in [Sharing the VM](#sharing-the-vm): at most 3 stacks at once, a VM slot per stack, enough free RAM;
- unique RUN names across repos (prefixed `it-`, `dl-`, `ra-`);
- the shared LLM key on the VM (`/root/shared/llm.env`, see [LLM key](#llm-key)): pointing runs at it, never printing it;
- the [clean-up](#clean-up) after every run: stacks, volumes, networks, images, folders and slots of its RUNs, plus its integration branches and worktrees (local only, never pushed).

The rest of this file is the reference for the runner, and for the maintainer working alone without the queue.

## Tests always run on the VM

Run pytest, the smoke test and the test stack on the VM, never locally on the Windows dev machine. The smoke test and the test stack need Docker, which only the VM has. pytest would run on Windows, but the machine is slow, has no admin rights and a heavy virus scanner, so a local run takes many minutes and looks like a hang. On the VM the whole suite takes under a minute.

## One command: `scripts/test-on-vm.sh`

From Git Bash in your checkout or worktree:

```sh
RUN=dr16 bash scripts/test-on-vm.sh                          # whole suite
RUN=dr16 bash scripts/test-on-vm.sh tests/test_config.py -x  # arguments go to pytest
```

The script does the steps below for you: it copies the working tree to `/root/dolibarr-mcp-server-$RUN`, runs pytest in a throwaway container `$RUN-pytest` (the Python image from the `Dockerfile`'s `FROM` line, `python:3.13-slim` until there is one, and the lock files), prints the output, removes the folder and the container again, also on failure or Ctrl-C, and exits with pytest's exit code. It refuses to start if the folder already exists, so it never touches another run. If the VM cannot be reached, it stops with ssh's error and exit code 255. pytest runs with `-q` unless you pass `-q` yourself, so the summary line always shows. Without `RUN` it picks a random `dev-<hex>` name. pytest needs no port. `VM_HOST`, `VM_KEY` and `VM_KNOWN_HOSTS` override the connection settings in the table above.

## One command for a test-stack run: `scripts/stack-on-vm.sh`

A whole run of `test-stack/` (start, checks, clean-up) from Git Bash in your checkout or worktree:

```sh
RUN=dl-ti02 bash scripts/stack-on-vm.sh                # Caddy stack, all checks
RUN=dl-ti02 bash scripts/stack-on-vm.sh --nginx        # nginx variant (adds compose.nginx.yaml)
RUN=dl-ti02 bash scripts/stack-on-vm.sh --groups oauth,rights   # only these check groups
RUN=dl-ti02 bash scripts/stack-on-vm.sh -- -v          # arguments after -- go to checks.py
```

It copies the working tree to `/root/dolibarr-mcp-server-$RUN`, takes a VM slot (see [Sharing the VM](#sharing-the-vm)), makes the test certificates, starts the stack as compose project `$RUN` with `TEST_TAG=$RUN` (images `dolibarr-mcp-test-dolibarr:$RUN`, `dolibarr-mcp-server:test-stack-$RUN`, `dolibarr-mcp-test-client:$RUN`), starts only the services the chosen check groups need (see below), waits until the setup is complete, prints the started containers with their RAM, runs the checks (`docker compose run --rm client python checks.py <groups>`) with their output straight through, and exits with their exit code. Afterwards it always takes the stack down with its volumes and removes its images, its folder and its slot, also on failure or Ctrl-C. The build and start output goes to a log on the VM; when the start fails, the script prints its last lines and the setup's log.

**Check groups** (`--groups`, default `all`): the checks are split into the groups `oauth`, `rights`, `ends`, `librechat` and `proxy` (see [test-stack/README.md](../../test-stack/README.md#check-groups)); these names are what the queue's `checks:` field takes. `--groups oauth,rights` runs only those groups (`rights`, `ends` and `proxy` bring `oauth` along, they build on it) and starts only the setup and its dependencies: neither LibreChat nor Mongo. Only a list with `librechat` (or `all`) starts them. Unknown names stop the script before it touches the VM (exit 2). Before the first LibreChat check the checks wait until LibreChat answers (up to 300 s, `LIBRECHAT_READY_TIMEOUT`).

| Exit code | Meaning |
| --- | --- |
| the checks' code | the checks ran (0: no check failed) |
| 2 | wrong usage, or this RUN is already in use on the VM (folder, slot or compose project) |
| 3 | the stack did not start (or not within `START_TIMEOUT`, default 1500 s) |
| 4 | no VM slot within `VM_SLOT_TIMEOUT` (default 1800 s) |
| 5 | the checks passed, but an LLM key showed up in a log, the check output or an image (see [LLM key](#llm-key)) |
| 255 | SSH failed: VM not reachable, key refused or connection lost |

RUN names must be unique on the whole VM, across repos: the compose project name is the bare `$RUN`, so a Dolibarr and an iTop run with the same name would share one project. Prefix the name with the repo: `dl-ti02` here, `it-ti02` in `itop-mcp-server`. Without `RUN` the script picks `dl-dev-<hex>`. It refuses to start (exit 2) when the folder exists, when any slot already has that RUN, or when the VM has a container, volume or network of compose project `$RUN`. `RUN` must not be `local`, `latest`, `test-stack`, `dolibarr-mcp-test` or `dolibarr-mcp-smoke`, the stack's shared default tags and project names. The stack publishes no ports, so runs need no port of their own. `VM_HOST`, `VM_KEY` and `VM_KNOWN_HOSTS` work as for `test-on-vm.sh`; `VM_SLOT_MAX` (3) and `VM_SLOT_MIN_MB` (3072) change the slot rule. For the LLM key see [LLM key](#llm-key): the script points the stack at the shared key file and never copies it; without that file the two chat checks report SKIP. The first start on an empty build cache takes some minutes; later starts are much faster.

The script is a port of `itop-mcp-server`'s `scripts/stack-on-vm.sh`: everything repo-specific (repo name, stack folder, compose files, prepare step, check command, image tags, reserved RUN names) sits in one block at its top, the rest is the same in both repos. Keep it that way when you change one of them.

If the script was killed so hard that its clean-up could not run (or SSH was gone), clean up by hand as described in [A ticket stack killed halfway](#a-ticket-stack-killed-halfway) and remove the slot: `rm -f /var/lib/test-vm-slots/dolibarr-mcp-server-$RUN.lease`.

### A ticket stack killed halfway

When `scripts/stack-on-vm.sh` or a by-hand run died without its clean-up (Ctrl-C that did not get through, lost SSH, killed shell), the stack of that run is still on the VM. Find it and take it down by its project name, which is the bare `$RUN`; nothing else is touched:

```sh
$SSH "docker ps -a --filter label=com.docker.compose.project=$RUN --format '{{.Names}} {{.Status}}'"   # what is left
$SSH "docker compose -p $RUN down --volumes --remove-orphans --timeout 5"      # containers, network, volumes, from any folder
$SSH "docker rmi \$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '(:|:test-stack-)$RUN\$')"   # the images tagged :$RUN or :test-stack-$RUN
$SSH "rm -rf /root/dolibarr-mcp-server-$RUN /var/lib/test-vm-slots/dolibarr-mcp-server-$RUN.lease"   # folder and VM slot
```

Check afterwards that the first command prints nothing. Use exactly your own `$RUN`: a prefix match would take down other runs. Without the folder, `docker compose -p $RUN down` still works; `docker compose config` (which the script uses to list the images) does not, hence the `docker images` lookup. A pytest container of a killed `test-on-vm.sh` run is `$SSH "docker rm -f $RUN-pytest"`.

## LLM key

The two chat checks (LibreChat answers whoami through the MCP server) need an LLM key. The VM has exactly one, shared by every repo and every agent; `itop-mcp-server` uses the same file:

| | |
| --- | --- |
| File | `/root/shared/llm.env` (folder `/root/shared` 0700, file 0600, root:root, put there by the maintainer) |
| Variables (chat checks) | `LITELLM_KEY`, `LITELLM_BASE_URL`, `LITELLM_MODEL`: the shared LiteLLM endpoint; its host name stays in the file, never in a repo, ticket or commit |

- This file is the only LLM key agents may use. Keys in other stacks' folders, `.env` files or containers are off limits, also when your chat checks would otherwise be skipped: never read, copy or reuse them.
- Never print the key, and never copy it into a repo, the run's folder, a ticket, a log or a commit. To see which variables the file has, print the names only: `$SSH "sed -n 's/=.*//p' /root/shared/llm.env"`.
- `scripts/stack-on-vm.sh` lets the stack read the file where it is: it sets `LLM_ENV_FILE=/root/shared/llm.env`, and `test-stack/compose.yaml` passes that file to LibreChat and the check client as an `env_file` (optional), so the key is in their environment at runtime only, not in an image or a file of the run. This works the same for the Caddy stack and the nginx variant (`compose.nginx.yaml` does not touch either service's `env_file`).
- Without the file, both chat checks report `SKIP no shared LLM key`, and the run's exit code ignores SKIPs. To try that, point `VM_LLM_ENV` at a path that does not exist (`VM_LLM_ENV=/root/shared/none.env RUN=dl-x bash scripts/stack-on-vm.sh`); never move or rename the real file.
- After the checks, also when a check failed, the script looks for the key's values on the VM in the start log, the logs of all the stack's containers, the check output and the config of the run's images, and prints only where it found one (exit 5 when the checks passed). By hand, compare on the VM without printing the key, e.g. `grep -qF "$(sed -n 's/^LITELLM_KEY=//p' /root/shared/llm.env | cut -c10-25)" <file> && echo found`.
- The chat model is set in `test-stack/librechat/librechat.yaml.tmpl`: one endpoint `LiteLLM` that reads `${LITELLM_KEY}` and `${LITELLM_BASE_URL}` from the shared file; LibreChat does not substitute `${LITELLM_MODEL}` in model names, so compose renders the template when LibreChat starts and fills in only the model name (twin: `itop-mcp-server` test-infra 09, same idea, no shared script). The Dolibarr assistant preset uses it. A chat check retries once on an empty answer and says so in its output.

The sections below are the manual steps, for the smoke test, the test stack and debugging.

## Connect

```sh
SSH="ssh -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts -o BatchMode=yes root@192.168.178.25"
$SSH
```

## Sharing the VM

This section is `vm-runner`'s job (see [Only `vm-runner` uses the VM](#only-vm-runner-uses-the-vm)). The VM's RAM, not the number of agents, limits how many runs fit at once. It has no swap; when RAM runs out, SSH stops answering for many minutes and the kernel kills containers of other runs.

- A **ticket stack** is a full test stack started for one ticket under its own RUN name. Starting one takes a **VM slot**.
- At most 3 ticket stacks run at the same time. Start one only if at least 3 GB are available: `$SSH "free -m | awk '/^Mem:/{print \$7}'"` must print 3072 or more. If not, wait or ask the orchestrator.
- `scripts/stack-on-vm.sh` keeps this rule for you: a **slot** is a lease file `/var/lib/test-vm-slots/<repo>-<RUN>.lease`, taken under `flock` on `/var/lib/test-vm-slots/.lock` only while fewer than 3 leases exist and at least 3072 MB are available; otherwise the script waits and says why. The folder is shared with `itop-mcp-server`, so the limit counts the stacks of both repos together. A lease whose run folder is gone for 15 minutes, or that is older than 3 hours, counts as left over by a killed run and is dropped. When you start a stack by hand, take a slot the same way or count the leases yourself.
- Take your stack down right after the run, also when it failed: `docker compose -p $RUN down -v --remove-orphans`, then remove your images (see Clean up).
- Never stop, change or read stacks, folders or files you did not create, including other stacks' `.env` and key files. Some stacks on the VM run permanently on purpose.

## Your own run: folder, project name, port

Several agents may use the VM at the same time. Every run picks one name of its own and uses it for its folder on the VM, its smoke test project name and its pytest container, plus a port of its own for the smoke test. Use lowercase letters, digits and `-` only (compose project names allow nothing else), e.g. `dr07` for ticket 07 of `dolibarr-repos`. For the port, take 18300 plus your ticket number (18200 and up belong to `itop-mcp-server` runs):

```sh
RUN=dr07                                # your own name: lowercase, digits, -
DIR=/root/dolibarr-mcp-server-$RUN          # your own folder on the VM
PORT=18307                              # your own smoke test port: 18300 + ticket number
$SSH "ss -ltn | grep -q ':$PORT ' && echo 'port $PORT is taken, pick another' || echo 'port $PORT is free'"
```

Never use the bare `/root/dolibarr-mcp-server` folder, the default smoke project `dolibarr-mcp-smoke` or the default smoke test port when others may be on the VM. pytest needs no port of its own: it runs in its own container with its own network.

## Copy the working tree over

This copies tracked and untracked files but not git-ignored ones, so uncommitted changes come along and `.env`, `compose.override.yaml`, `certs/`, `logs/` and `.venv/` stay behind. It replaces only your own folder:

```sh
git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - \
  | $SSH "rm -rf $DIR && mkdir $DIR && tar -xf - -C $DIR"
```

The copy has no `.git` folder (`stack-on-vm.sh` and `test-on-vm.sh` copy the same way). What does not work because of that:

- Every `git` command in the VM folder fails (`not a git repository`): no `git status`, `diff` or `log` there. Do your git work on the dev machine and copy the result over.
- A restoauth **checkout** as `RESTOAUTH_LOCAL` does not work on the VM: the build needs the checkout's `.git` folder to build the release ZIP with `git archive` (see [test-stack/README.md](../../test-stack/README.md#restoauth-from-a-local-zip-or-checkout)). Copy a built ZIP instead.
- Git-ignored files are not copied either: put nothing a run needs into `.env`, `compose.override.yaml`, `certs/`, `logs/` or `.venv/` (the stack makes its own certificates).

`.gitattributes` gives every text file LF line endings, also on Windows with `core.autocrlf=true`, so the copy runs on Linux as-is. A checkout made before that rule existed keeps its CRLF files until they are written again; `git ls-files --eol | grep -v w/lf` lists them. To rewrite them, commit or stash your changes first, then run this in the checkout:

```sh
git ls-files -z | xargs -0 rm -f -- && git checkout -- .
```

## Run pytest

The full suite in a throwaway `python:3.13-slim` container with the locked dependencies, the same steps as in the README. Your folder is mounted read-only and copied inside the container, so the install leaves nothing behind in it, and `--rm` removes the container afterwards:

```sh
$SSH "docker run --rm --name $RUN-pytest -v $DIR:/src:ro python:3.13-slim sh -c '
  cp -r /src /work && cd /work &&
  export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 &&
  pip install -q --no-deps -r requirements.lock -r requirements-build.lock &&
  pip install -q --no-deps --no-build-isolation -e . &&
  pip install -q pytest==8.4.2 &&
  pytest -q'"
```

Pass pytest arguments at the end as usual, e.g. `pytest -q tests/test_config.py`. The container needs internet access to PyPI.

## Run the smoke test

```sh
$SSH "cd $DIR && SMOKE_PROJECT=$RUN SMOKE_PORT=$PORT bash scripts/smoke-test.sh"
```

The script tags its image `dolibarr-mcp-server:<version>-$RUN`, so it never replaces another run's image or the shared `dolibarr-mcp-server:<version>` tag. When it ends it stops its containers (`docker compose down`) and deletes its `.smoke` work folder, but it keeps the image.

## Run the test stack

The full stack from `test-stack/` (see its README), under your own project name and image tag. It publishes no ports, so it needs no port of its own:

```sh
$SSH "cd $DIR/test-stack && sh make-certs.sh && TEST_TAG=$RUN docker compose -p $RUN up -d --build"
$SSH "cd $DIR/test-stack && docker wait $RUN-setup-1; docker compose -p $RUN logs setup | tail -15"
```

`docker wait` prints `0` when the setup ended with "setup complete". Then the end-to-end checks (OAuth flow, rights, how a connection ends and LibreChat, about two and a half minutes; exit code 1 if a check failed):

```sh
$SSH "cd $DIR/test-stack && TEST_TAG=$RUN docker compose -p $RUN run --rm client"
```

The two LibreChat chat checks need the shared LLM key (see [LLM key](#llm-key)) and report SKIP without it. By hand, let compose read it in place: put `LLM_ENV_FILE=/root/shared/llm.env` in front of `docker compose` in the `up` and `run` commands above (and in any `restart librechat`). Never copy the file into your folder, never print it and never commit it.

For the nginx variant (see the test stack README), add `-f compose.yaml -f compose.nginx.yaml` after
`-p $RUN` in the `up`, `run` and `down` commands. It uses `nginx:1.30.5` as base image.

If Docker Hub answers a pull with `429 Too Many Requests` (anonymous pull limit, shared by every run
on the VM), pull the same official image from Google's mirror and tag it with its Docker Hub name,
e.g. `docker pull mirror.gcr.io/library/nginx:1.30.5 && docker tag mirror.gcr.io/library/nginx:1.30.5
nginx:1.30.5`; base images of the builds (`python:3.13.18-slim`) go the same way.

### restoauth from a local ZIP or checkout

To test a restoauth change that has no release yet, point `RESTOAUTH_LOCAL` at a folder on the Docker host before the build. The stack's `dolibarr/Dockerfile` takes a release ZIP from GitHub by default; `RESTOAUTH_LOCAL` overrides that. Set it for `up` too, or `up --build` falls back to the release. The build log names the source (`restoauth: local ZIP ...`, `restoauth: building ... from the local checkout at <commit>`).

| `RESTOAUTH_LOCAL` is | The build |
|---|---|
| a folder with `module_restoauth-<version>.zip` in it (e.g. restoauth's `dist/` after `bash scripts/build-release-zip.sh vX.Y.Z`) | takes that ZIP as it is |
| a restoauth git checkout (with its `.git` folder) | builds the ZIP from the checkout with `git archive` (tracked files with their uncommitted changes, no untracked files, no `export-ignore` files) |

`<version>` is `RESTOAUTH_VERSION` (pinned in `dolibarr/Dockerfile`); for another version pass `--build-arg RESTOAUTH_VERSION=X.Y.Z`. The build stops if the folder has neither ZIP nor checkout, or if the module descriptor in the ZIP carries another version. On the VM, the folder must be on the VM: copy the ZIP there first, e.g. into your run folder.

```sh
# on the VM, for a run named $RUN:
$SSH "mkdir -p $DIR/restoauth"
scp -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts module_restoauth-*.zip root@192.168.178.25:$DIR/restoauth/
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN RESTOAUTH_LOCAL=$DIR/restoauth LLM_ENV_FILE=/root/shared/llm.env && sh make-certs.sh >/dev/null && docker compose -p $RUN up -d --build --quiet-pull"
```

**The checkout mode does not work on the VM.** The copy to the VM has no `.git` folder (see [Copy the working tree over](#copy-the-working-tree-over)), and the restoauth checkout mode needs `.git` to build the ZIP with `git archive`. Copy a built ZIP instead.

### Re-run after a settings change (cheap)

`stack-on-vm.sh` always takes the stack down at the end, so a re-run through it starts from scratch (5 to 10 minutes). When you only changed a setting and want to see the checks again, keep the stack and restart just the service that reads the setting. This is by hand, so you take the slot and clean up yourself: start the stack like the script does, **under a RUN name of its own**, and take it down when you are done (see [Clean up](#clean-up)).

```sh
RUN=dl-ti04; DIR=/root/dolibarr-mcp-server-$RUN
# once: copy (see "Copy the working tree over"), take a slot (lease file, see "Sharing the VM"), then
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && sh make-certs.sh >/dev/null &&
      docker compose -p $RUN up -d --build --quiet-pull"       # returns when the setup is complete
# after each change: copy only the changed files, WITHOUT the rm -rf of the full copy (it would remove certs/)
git diff --name-only --diff-filter=d HEAD | tar -T - -cf - | $SSH "tar -xf - -C $DIR"      # plus new files: git ls-files -o --exclude-standard; deleted files: rm them in $DIR by hand
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && docker compose -p $RUN up -d --build dolibarr"      # recreates the container: new TEST_* values and a rebuilt configure.php
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && docker compose -p $RUN run --rm client python checks.py"      # or: ... checks.py <groups>
```

The settings live in `dolibarr/configure.php` and in the `dolibarr` container's environment (`TEST_*` in `compose.yaml`). `configure.php` is copied into the Dolibarr image (`dolibarr/Dockerfile`) and run by `dolibarr/50-test-stack.sh` on every start of the container. So after a settings change the container has to be **recreated**, not restarted: `docker compose restart` keeps the old environment and the old image. Use `up -d dolibarr` for a changed `TEST_*` value and `up -d --build dolibarr` for a changed `configure.php`, then wait until it is healthy again (`docker compose -p $RUN ps dolibarr` shows `healthy`); the checks wait for the setup's healthcheck themselves. A changed `librechat.yaml.tmpl` or `librechat.env` needs `restart librechat` (or `up -d librechat` for env changes); changes to the MCP server's `src/` need `up -d --build mcp`. Checks run several times on one stack need no wait for LibreChat's login limit: the test stack raises it (see [test-stack/README.md](../../test-stack/README.md#librechats-login-limit)); with LibreChat's normal limit (`TEST_LIBRECHAT_LOGIN_MAX=7 docker compose -p $RUN up -d librechat`) a re-run of the group `librechat` waits up to five minutes for the window, and `restart librechat` resets the count.

Take it down again with its volumes and its images:

```sh
$SSH "cd $DIR/test-stack && docker compose -p $RUN down --volumes --remove-orphans && docker rmi dolibarr-mcp-test-dolibarr:$RUN dolibarr-mcp-server:test-stack-$RUN dolibarr-mcp-test-client:$RUN"
```

Keep the pulled base images (`dolibarr/dolibarr`, `mariadb`, `caddy`, Keycloak, `mongo`, `librechat/librechat`, `alpine`): other runs use them too.

## Clean up

Remove only what you created yourself, and nothing else:

```sh
$SSH "docker rmi dolibarr-mcp-server:\$(sed -n 's/^__version__ = \"\(.*\)\"\$/\1/p' $DIR/src/dolibarr_mcp_server/__init__.py)-$RUN; rm -rf $DIR"
```

If a run was killed halfway, also take its containers and networks down first: `$SSH "docker compose -p $RUN down --volumes --remove-orphans"` (works from any folder, by project name alone), and `$SSH "docker rm -f $RUN-pytest"` for a pytest container.

Keep the shared things in place, even if they look unused: the `python:3.13-slim` image, the `dolibarr-mcp-server:<version>` tag, and other runs' images, containers, networks and folders. Never run `docker system prune`, `docker image prune -a`, `docker builder prune` or `docker rm -f $(docker ps -aq)`: they hit every run on the VM, not just yours.

## Notes

- The VM exists only for testing and may be wiped or recreated at any time. If the host key changed, ask the maintainer before you trust the new one.
- Commands run as root there. For the default admin path, `./logs` must still be `chown 10001:10001` (see `.env.example`). The smoke test does not need this; it uses its own log folder.
