# E2E test artifacts

## What's here

- `llm_recordings.json` - Pre-recorded LLM responses, one per pipeline
  node. Keys map to the node's system-prompt discriminator (see the
  `_pick_recording` heuristic in `tests/test_pipeline_e2e.py`).

## Why

The E2E test at `tests/test_pipeline_e2e.py` runs the *entire real
pipeline* (Setup, Router, Planner, Coder with Best-of-N, Tester,
Reviewer, PR Creator) end-to-end against `tests/fixtures/seed_repo` -
but with LLM calls, GitHub API, and `git push` swapped out for these
recordings and small fakes. That way anyone can `make test-e2e` with:

- **no API keys** (NIM / Gemini / GitHub all mocked)
- **no external repositories** (seed_repo is bundled in-repo)
- **no cost, no rate limits, no network flakiness**

## Updating the recordings

If you change the seed_repo bug, the pipeline prompts, or Best-of-N
parameters, re-record:

1. Point at a real LLM temporarily by removing the mock in the test.
2. Run the pipeline against seed_repo end-to-end.
3. Capture the exchanges via log inspection or by instrumenting
   `llm.provider.llm.chat` to print each request/response.
4. Save the responses back into `llm_recordings.json` under the
   right keys.

For most changes, editing the recordings by hand is faster than
re-recording - each entry is human-readable JSON or markdown.
