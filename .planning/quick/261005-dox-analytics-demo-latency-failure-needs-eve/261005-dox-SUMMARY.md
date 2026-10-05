# Quick 261005-dox Summary

Failure needs now run on a 15 s fast tick (no ClickHouse), and a DOWN host covered by an open incident gets its host-level need (D-27 reversed for host-DOWN only).

## Commits
- a28364c: rules.py host-DOWN reversal plus `evaluated_sources` anti-flap in `NeedTracker.update`
- 95b39b0: service.py `run_cycle(now, slow=...)`, fast/slow deadlines in `run_forever`, publish-on-change `_need_sigs`
- e37c226: D-13/D-27 amendments in 14.2-CONTEXT.md and three docs

## Verification (observed)
- `uv run pytest tests/ -q`: 1094 passed
- `uvx ruff check analytics tests/test_analytics_rules.py tests/test_analytics_service.py`: clean
- Task 1 tests failed before implementation (16 failed), pass after.
- Not verified: live deploy (not requested, no container touched).

## Dashboard
Searched dashboard-react/src for incident-based dropping of needs: none found. No dashboard change.

## Deviations
Worktree base was 71e54b9, not the expected 35a818b; reset hard to 35a818b per the branch check. No other deviations.

## Notes
- Fast ticks publish only needs whose payload (minus generated_at) changed; slow cycles republish all.
- Deploy needs a full `podman compose down` then `up -d` (documented).
