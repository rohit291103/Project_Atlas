"""Operator tooling: standing up and checking an environment, never running one.

Nothing in `src/atlas/` imports from here, and nothing here is part of the
product -- `seed_demo_jira.py` writes to Jira precisely so Atlas never has to,
and `verify_rls.py` proves the tenant boundary holds against a real Postgres.

This file exists for one reason: `seed_test_workspace.py` builds the fixture the
browser suite asserts against, and those properties are worth testing
(`tests/test_seed_test_workspace.py`). Making the directory a package is what
lets a test import it under the same module name mypy checks it under.
"""
