# Development

Install the test dependencies once (`pytest-cov` is required by `pyproject.toml`'s `addopts`;
the plain `pytest` command below fails before a test runs without it):

```
pip install -r requirements-dev.txt
```

```
python3 -m pytest tests/ -q
```

**The supported floor is Python 3.9**, declared in `pyproject.toml` as
`[project] requires-python = ">=3.9"` and nowhere else. CI runs the suite on ubuntu, macOS and
Windows across Python 3.9-3.12; that is what the code is *demonstrated* on, which is a different
question from what it *supports*, and reading the two as one is what #410 filed. The floor is wider
than the code needs — nothing tracked here uses a syntax or standard-library feature above 3.7 — and
it is set at 3.9 because 3.9 is the oldest version anything here has ever been run on.

The badge in `README.md`, the matrix, the `Python X.Y compatible` line eight modules under
`scripts/` carry, and the oldest explicit `python3.N` in `scripts/doctor.sh`'s interpreter walk are
all *derived* from that key. None of them can read a manifest at parse time, so
`tests/test_python_floor_410.py` is what makes them agree. A green macOS run is not evidence on its
own.

A separate ubuntu leg runs `bash -n` and `shellcheck -S warning` over every tracked shell source.
Which files those are is derived rather than listed — `python3 scripts/shell_sources.py` prints the
list, selecting by extension or by shebang so an extensionless script is covered by the commit that
adds it. It exits non-zero when it matches nothing, so an empty selection fails the leg instead of
linting no files and passing. A tracked file that is in the index and not on disk — what an
uncommitted delete looks like, and what the changelog fold leaves behind until the release commit —
is named on stderr and does not fail the leg; only a file that is there and will not read does.

That leg installs nothing. `shellcheck` ships in the `ubuntu-latest` runner image, and fetching it
anyway put a package-mirror round trip inside the job's `timeout-minutes`, which is what took the leg
— and with it every pull request — down for a day (#303). If the binary is ever missing the step says
so and exits `4`, rather than collecting one `command not found` per file into the same status a real
finding uses.

`python3 scripts/transcript_refusals.py` counts refused tool calls across this machine's own agent
transcripts, by refusal class, by model and by the batching lever #313 measured. Its own third state
is the point: a directory with no transcripts must not read like one full of transcripts that
refused nothing. The script's own docstring carries the full field list.

`python3 scripts/review_return.py -` classifies what a review spawn actually handed back, in six
states from `states-findings` to `could-not-classify` -- built for `referred-not-stated`, a message
that gestures at findings without stating them, which two rounds of brief language (#275, #296,
#392) failed to prevent. `agents/developer.md` is where it is actually driven from; the script's own
docstring has the full mechanism, including why input is framed rather than read raw (#404).

`python3 scripts/tree_snapshot.py snapshot` / `... compare --before -` is the same shape one review
step over: a receipt across the spawn itself, not just its return value. A reviewer already reverted
a tracked file in place and a self-cleaning scratch write left no trace, neither with a ref move or a
reflog entry (#769) -- a brief telling the spawn not to mutate is not a mechanism, so
`agents/developer.md` snapshots the tree before spawning and compares after, in three states:
`clean`, `mutated` (names what changed), `could-not-compare`. It cannot see a write created and
deleted before the `compare` call runs, which is stated in its own docstring rather than assumed.

`scripts/batch_hint.py` is a `PostToolUse` hook (`hooks/hooks.json`) that flags a run of 3 or more
consecutive single-op read-only supertool calls with one line naming the collapsed form, and only
that -- it never blocks. It exists because the equivalent instruction in prose, in `agents/
developer.md`, measured at zero effect across 612 transcripts and a controlled A/B (#490): a hook
costs nothing on a clean run, where prose is charged on every turn whether or not it ever applies.

`scripts/agent_budgets.py` records a size budget for each `agents/*.md` definition -- every byte
there is re-read on every turn of every lane that runs it -- and `tests/test_agent_definition_
budget_491.py` fails when one crosses it. `CLAUDE.md` carries the current sizes and the
replace-don't-append rule that goes with them (#491).

`python3 scripts/select_issues.py --preflight PATTERN --path FILE_OR_DIR` searches the tree for a
pattern the issue names, in three states -- `matched`, `not-matched`, `could-not-search`, the last
of which must never render as the second -- so a dispatch decision can tell an issue whose fix
already shipped from one still genuinely open before an agent is briefed for it (#457). A file that
fails to decode as UTF-8 is checked for a UTF-16 byte-order mark first -- a NUL-byte test alone
cannot tell UTF-16 source from binary, since UTF-16-encoded ASCII carries a NUL per character, so a
BOM-carrying file forces `could-not-search` rather than a silent `not-matched` (#738). Absent a BOM,
it is told apart by whether it contains a NUL byte, the same signal `git diff`/`grep -I` use to call
a file binary: present (a `__pycache__/*.pyc`, on every Python tree) it counts as `skipped_files`,
reported always and never forcing `could-not-search` on its own; absent, the decode failure is
genuinely ambiguous -- real source in another encoding fails the same decode -- and it still forces
`could-not-search`, the conservative answer rather than a guess (#717). BOM-less UTF-16 is a
separate, worse gap the BOM check does not close -- ASCII-content UTF-16 with no mark decodes
successfully as UTF-8 outright and never reaches the decode-failure branch at all, so it returns a
silent `not-matched`; left as a documented follow-up rather than fixed here. The receipt also names
`roots`, the paths actually searched, on every state including `could-not-search`, so the scope
travels into a brief along with the answer instead of being retyped from memory as a summary (#727).

`python3 scripts/transcript_refusals.py` also now reports `turns_over_threshold_count`/`_share`
against a measured 140-turn threshold and `decile_bytes`/`first_fifth_byte_share`, the two lane-cost
findings #498 measured across 612 transcripts -- read after a lane completes, never surfaced to the
one running.

`pyproject.toml`'s `addopts` carries `--durations=25` (#881), so every invocation of
`python3 -m pytest tests/ -q` -- CI's or a contributor's -- ends with the 25 slowest tests and their
wall time. Before this, every CI leg reported one total and a pass count, and a 4-second test and a
4-millisecond test were indistinguishable in every artifact CI produced. This is step 1 of #881 only
-- making the question answerable -- not an optimisation; no test was changed to get here.

`tests/duration_report_plugin.py` -- registered via `tests/conftest.py`'s `pytest_plugins`, the
same way `must_assert_plugin` is -- is #910's answer to the question #881 only made answerable:
every run now also prints the slowest single test's **share** of total suite time (a ratio, since
an absolute second count says more about the runner than about the test) and compares it against a
recorded baseline at `tests/duration-baseline.json`, in three states named explicitly in the
output -- `measured`, `no-baseline` (nothing recorded yet, or the file could not be read), and
`could-not-measure` (nothing was collected this session at all, e.g. a `--collect-only` run) -- so a
step that saw nothing can never print like a suite with no hot test. Nothing here fails a build on
a duration or a share; it only reports. The actual computation lives in `scripts/test_durations.py`,
imported by the plugin rather than duplicated. Run `pytest --record-duration-baseline` to record the
current numbers as the new baseline -- a deliberate act, never done on an ordinary run.
