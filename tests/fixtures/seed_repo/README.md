# seed_repo

Minimal Python project used as the target of the local E2E test at
`tests/test_pipeline_e2e.py`. Contains a deliberate divide-by-zero bug
in `src/calc.py` and a failing test in `tests/test_calc.py` that
represents the "issue" the agent has to fix.

Copied into a fresh `tmp_path` and turned into a real git repo by the
test fixture. Not itself under source control as a sub-repo.
