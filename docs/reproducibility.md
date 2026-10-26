# Reproducibility record (REL-0)

Status: **tag created and pushed — 2026-10-26.** The maintainer confirmed
commit `cdf5c38` and the name `v1.2.0-thesis`. This annotated tag fixes the
historical thesis baseline; it does not certify its physics as correct.
The tag points to the original code, not to this subsequently completed record.

## Tagged commit

| Item | Value |
|---|---|
| Tagged commit | `cdf5c38e975871debf64eb6d810e78a08165c381` |
| Short hash | `cdf5c38` |
| Commit subject | `Use 4-space indentation everywhere` |
| Commit date | 2026-10-06 01:35:06 +0800 |
| Branch at verification | `parser-streaming` (HEAD, also `origin/parser-streaming`) |
| Tag | `v1.2.0-thesis` (annotated) |
| Tag created | **yes** — 2026-10-26 |
| Tag pushed | **yes** — 2026-10-26 |

The maintainer confirmed this commit as the thesis baseline and approved
creation and push of the proposed tag name on 2026-10-26. Remote tag target
verification (`git ls-remote --tags origin 'refs/tags/v1.2.0-thesis*'`)
returned the exact commit above as the peeled target.

## Verification run

Run in a detached temporary worktree of the candidate commit (so the main
working tree, including untracked agent docs, cannot affect the result):

```bash
WT=$(mktemp -d /tmp/lkpr-rel0-XXXXXX)
git worktree add --detach "$WT" cdf5c38e975871debf64eb6d810e78a08165c381
cd "$WT"
HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py
```

Result (2026-10-20, this machine):

```
42 passed, 0 failed
```

Covered by that run: mapping/display/CLI suites, fast numeric regression,
slow RDF/MSD goldens (`LKPR_SLOW=1`), log-merge, dump-reader and shared-pass
engine tests. ASE-dependent fair-comparison coordinate checks were skipped.

### Tag verification (2026-10-26, measured)

Re-ran `HOME="$(mktemp -d /tmp/opencode/rel0-home-XXXXXX)" LKPR_SLOW=1
python tests/run.py` in the clean detached checkout at `cdf5c38`, the exact
commit subsequently verified as the remote tag's target. The runner again
reported **42 passed, 0 failed**, including the RDF/MSD golden comparison.
Python was 3.14.4 and NumPy 2.3.5; SciPy was available. ASE, matplotlib,
pandas, MDAnalysis, pytest and the native parser were absent.
The log is `/tmp/opencode/rel0-20261026-tests.log` (local evidence, not
part of the repository).

Three tests returned early and were counted as PASS by the historical runner:
- `test_all_force_fields_build_identical_coordinates` — ASE absent.
- `test_wall_does_not_depend_on_the_force_field` — ASE absent.
- `test_native_parser_matches_loadtxt` — native parser not built.

The tag preserves known historical defects, including MSD type reselection
and slab-only default unwrapping (PHYS-1/2). Passing goldens prove the
baseline is reproduced, not that those numerical values are physically correct.
No fixtures or goldens were changed.

### Known caveats of this verification

- `tests/run.py` still counts early-`return` skips as PASS (BACKLOG TEST-1).
  In this clean worktree the optional native parser was **not built**
  (`lammps_post._dumpparse` absent, `_native is None`), so
  `test_native_parser_matches_loadtxt` returned early and was counted as
  PASS. The NumPy `loadtxt` path — the reference implementation — was fully
  exercised. To verify the native path too, run `native/build.sh` in a
  scratch copy first (never commit the `*.so`).
- Plotting is not covered: `matplotlib`, `pandas`, `MDAnalysis`, `ase` and
  `pytest` are not installed in this environment (see below). Analysis and
  parsing goldens are covered; figures are not.
- Real-data checks done earlier on this branch (CM4288 ReaxFF, CM3288) are
  not part of the committed suite and are not reproduced by the command
  above; they were manual benchmarks, not golden tests.

## Environment

| Item | Value |
|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel `7.0.0-38-generic` x86_64 |
| Python | 3.14.4 (`/home/kim/.local/bin/python`, GCC 15.2.0) |
| pip | 25.1.1 |
| NumPy | 2.3.5 |
| SciPy | 1.16.3 |
| rich | 13.9.4 |
| setuptools | 78.1.1 |
| pandas / matplotlib / MDAnalysis / ase / pytest | not installed |
| Native dump parser | not built in the verification worktree (NumPy path used) |

Full `python -m pip freeze` at verification time (119 lines; includes
system packages of this machine — for a thesis environment, prefer a clean
venv and regenerate this list there):

```text
aptdaemon==2.0.2
asn1crypto==1.5.1
attrs==25.4.0
autocommand==2.2.2
babel==2.17.0
bcc==0.35.0
bcrypt==5.0.0
beautifulsoup4==4.14.3
blinker==1.9.0
Brlapi==0.8.6
CacheControl==0.14.3
cclib==1.8.1
certifi==2026.1.4
chardet==5.2.0
click==8.1.8
command-not-found==0.3
configobj==5.0.9
crit==4.2
cryptography==46.0.5
cssselect==1.4.0
cupshelpers==1.0
dasbus==1.7
dbus-python==1.4.0
decorator==5.2.1
defer==1.0.6
distro==1.9.0
distro-info==1.15
gpg==2.0.0
gyp-next==0.16.2
h5py==3.15.1
h5py._debian_h5py_serial==3.15.1
html5lib-modern==1.2
httplib2==0.22.0
idna==3.11
inflect==7.5.0
jaraco.context==6.0.1
jaraco.functools==4.1.0
jaraco.text==4.0.0
Jinja2==3.1.6
jsonpatch==1.32
jsonpointer==2.4
jsonschema==4.19.2
jsonschema-specifications==2023.12.1
language-selector==0.1
launchpadlib==2.1.0
lazr.restfulclient==0.14.6
lazr.uri==1.0.6
libevdev==0.13.1
libpass==1.9.3
linkify-it-py==2.0.3
louis==3.36.0
lxml==6.0.2
markdown-it-py==3.0.0
MarkupSafe==3.0.3
mdurl==0.1.2
mechanize==0.4.10
meson==1.10.1
more-itertools==10.8.0
msgpack==1.1.2
netaddr==1.3.0
netifaces==0.11.0
numpy==2.3.5
oauthlib==3.3.1
olefile==0.47
packaging==26.0
periodictable==2.0.2
pexpect==4.9.0
pillow==12.1.1
platformdirs==4.9.4
pooch==1.9.0
protobuf==4.21.12
psutil==7.1.0
psutils==3.3.14
ptyprocess==0.7.0
puremagic==1.30
pycairo==1.27.0
pycriu==4.2
pycryptodomex==3.20.0
pycups==2.0.4
Pygments==2.19.2
PyGObject==3.56.2
PyJWT==2.10.1
pyparsing==3.3.2
pypdf==6.9.2
pyserial==3.5
python-apt==3.1.0+ubuntu1
python-debian==1.0.1+ubuntu2
pyudev==0.24.3
pyxdg==0.28
PyYAML==6.0.3
referencing==0.36.2
requests==2.32.5
rich==13.9.4
rpds-py==0.27.1
scipy==1.16.3
scour==0.38.2
setproctitle==1.3.7
setuptools==78.1.1
six==1.17.0
soupsieve==2.8.3
systemd-python==235
tinycss2==1.5.1
tqdm==4.67.3
trash-cli==0.24.5.26
typeguard==4.4.4
typing_extensions==4.15.0
ubuntu-drivers-common==0.0.0
ubuntu-pro-client==8001
uc-micro-py==1.0.3
ufw==0.36.2
unattended-upgrades==0.1
urllib3==2.6.3
wadllib==2.0.0
webencodings==0.5.1
wheel==0.46.3
xdg==5
xkit==0.0.0
xlrd==2.0.2
zipp==3.23.0
```

## Fixtures (reference system #1, Fe-O ACE)

Committed under `tests/fixtures/ace_examples/` (never modify fixtures):

| Path | Used for |
|---|---|
| `tests/fixtures/ace_examples/regular_MD/traj.dump` | main golden fixture (RDF/MSD/spin, ff_info) |
| `tests/fixtures/ace_examples/regular_MD/log.lammps` | log parsing |
| `tests/fixtures/ace_examples/regular_MD/POSCAR_Fe3O4_FeM.lmp` | structure reference |
| `tests/fixtures/ace_examples/regular_MD/run_md.lammps` | input reference |
| `tests/fixtures/ace_examples/spin_equilibration_MD/traj.dump` | spin-equilibration fixture |
| `tests/fixtures/ace_examples/spin_equilibration_MD/log.lammps` | log parsing |
| `tests/fixtures/ace_examples/ACE_Fe-O.yace`, `ACE_Fe-O.yaml` | ACE potential reference |
| `tests/fixtures/ace_examples/simulation_summary.md` | fixture provenance |

## Reproduction commands

```bash
# 1. Get the exact tagged state in a scratch worktree
WT=$(mktemp -d /tmp/opencode/lkpr-thesis-XXXXXX)
git worktree add --detach "$WT" v1.2.0-thesis
cd "$WT"

# 2. (Recommended) clean environment
python -m venv .venv && . .venv/bin/activate
pip install -e .[all,dev]

# 3. Verify goldens reproduce
HOME="$(mktemp -d)" python tests/run.py                # fast
HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py    # + RDF/MSD goldens

# 4. Optional: native parser (same results, faster)
native/build.sh
HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py
```

Expected: `42 passed, 0 failed` at the candidate commit in the environment
above. Test counts may change after TEST-1 (skip reporting) lands; compare
golden results, not just the count.
