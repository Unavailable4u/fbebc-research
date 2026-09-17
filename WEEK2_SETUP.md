# Week 2 setup — run this on your WSL2 box

Everything below was written and unit-tested in an environment with no
Docker daemon (86/86 tests green: `pytest` from repo root). What's untested
is anything that needs a real kernel: the sandbox's actual isolation
guarantees. That's the part only you can verify right now.

## 0. First, check which Docker you're actually running

This matters before anything else, because it decides whether your ADV
Tier B results (network isolation, filesystem isolation, pids/memory
limits) mean what the paper will claim they mean.

```bash
docker info --format '{{.OperatingSystem}}'
docker context ls
cat /proc/version
```

If `docker context ls` shows `desktop-linux` as the active context, or
`/proc/version` mentions `microsoft-standard-WSL2` but `docker info` shows
something like `Docker Desktop`, you're most likely running through **Docker
Desktop's WSL2 integration** — the `docker` CLI in your Ubuntu WSL2 distro is
talking to a daemon living in Docker Desktop's own `docker-desktop` /
`docker-desktop-data` WSL distros, not a daemon native to your Ubuntu
distro. Since 2020 that daemon does share the real WSL2 Linux kernel (it's
much closer to native than the old Hyper-V backend, and not the same
problem as Docker Desktop on macOS), so it isn't necessarily broken for
this purpose — but it's not exactly what research-program-guide §1.3 asks
for ("Linux or WSL2, not macOS/Windows Docker Desktop"), and it adds a
layer (Docker Desktop's own networking/proxy setup) between your container
and the host that the guide's authors didn't have in mind.

The clean way to remove all doubt: install Docker Engine **natively inside
your Ubuntu WSL2 distro**, so `dockerd` runs as a normal Linux daemon on the
same kernel your tests run on, with no Docker Desktop layer at all:

```bash
# Inside your Ubuntu WSL2 distro (not Docker Desktop's installer):
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# close and reopen your WSL2 terminal, then:
sudo service docker start   # WSL2 doesn't run systemd by default on older images
docker run --rm hello-world
```

Either way, **write down which setup you used** — it belongs in the paper's
Methods section next to the ADV suite results, per the same honesty
discipline you've already applied to the Levenshtein-vs-Zhang-Shasha
substitution.

## 1. Pull this branch's new files into your clone

The files described below are new; nothing from Week 1 was modified except
`STATUS.md`. Pull them into your working copy however's easiest for you
(patch, direct copy, or re-running whatever produced Week 1 against this
transcript) and confirm:

```bash
pytest -v   # should show 86 passed, all in tests/unit
```

## 2. Pin the base image

```bash
chmod +x docker/pin_image.sh
./docker/pin_image.sh
```

Paste the printed `python:3.12-slim@sha256:...` line into
`delta/evaluation/launcher.py`'s `PINNED_IMAGE` constant, replacing the
plain tag. Record the same digest in your run notes — this is the
`image_digest` value every ledger record will carry from now on.

## 3. Smoke-test the sandbox for real

```bash
pytest tests/integration -v
```

Expect:
- `test_basic_roundtrip` — passes trivially, confirms the whole path works.
- `test_network_is_actually_isolated` — passes if `--network=none` is real.
- `test_filesystem_is_actually_read_only` — passes if `--read-only` is real.
- `test_pids_limit_contains_fork_bomb` / `test_memory_limit_contains_bomb` —
  deliberately adversarial; read their docstrings once before running them
  the first time. They should finish in well under `timeout_s` and never
  touch host resources — the cgroup limits are on the *container's* cgroup.
- `test_score_smuggling_rejected_by_host` — confirms I3 (score
  non-authorship) is enforced host-side, not something the container itself
  needs to know or care about.

If any of the isolation tests fail, that's real signal about your specific
Docker setup (see step 0) — not a code bug to paper over. Stop and fix the
environment before trusting any further ADV results.

## 4. What's still missing after this (Week 2 Day 12-14)

Two things, deliberately not built yet:

1. **The Σ client.** A thin wrapper around the Gemini free tier: send
   `(parent_src, task description, prior rejection reason if any)`, get back
   a SEARCH/REPLACE diff, hand it to `orchestrator.admit_candidate()`. Needs
   your own API key — nothing in this repo should ever have one hardcoded.
2. **The generation loop.** Nothing yet calls `admit_candidate()` →
   `evaluate()` repeatedly, tracks an elite band, or turns a rejection's
   typed code + detail into the next prompt's feedback. `evaluate.py`'s
   docstring is explicit about the one hard rule the loop must respect:
   stop admitting new candidates the moment `IntegrityViolation` is raised,
   don't just skip that one candidate.

Once those two exist and you've run a handful of real generations on the
binpacking warm-up task (per the guide: pipeline-debugging only, not
reported in the paper), you're ready for Week 3: switch to circle packing
for real, and run the scoped ADV suite's Tier C cases (reward-hacking)
against a live container instead of the host-side unit tests that stand in
for them today.
