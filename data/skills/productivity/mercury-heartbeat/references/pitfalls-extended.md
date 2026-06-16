# Extended Pitfalls for Mercury Heartbeat

This file contains pitfalls discovered after the main SKILL.md reached its size limit.
The main SKILL.md references this file for additional known issues.

## Pitfalls

### ABORTED watch_status with live RAM fallback produces misleading abort analytics (discovered 2026-05-29)

**Problem:** When a cycle is ABORTED by preflight (RAM > threshold), `run_cycle.py`'s live RAM fallback fills `ram_pct` and `health_score` in the metrics entry with values from *after* the abort — by which time RAM may have dropped back to normal (e.g., 27-33%). The `watch_status` stays `ABORTED`. This causes `abort_pattern_analyzer.py` to report an "abort RAM range: 17.5% - 38.7%" that looks like low-RAM cycles are being aborted for no reason, when in reality they were aborted at high RAM that later dropped.

**Impact:** Makes abort pattern analysis unreliable. The `abort_pattern_analyzer` recommendations (like "increase threshold from 85 to 95") are based on wrong data — the actual abort-time RAM was higher than what the metrics show.

**Detection:** If `watch_status == 'ABORTED'` but `ram_pct < max_ram_pct`, the `ram_pct` field is a live fallback, not the actual abort trigger value. Check: count how many ABORTED entries have `ram_pct` below threshold. If most do, the fallback is masking the real abort cause. In the observed case, 60/100 entries were ABORTED with an average `ram_pct` of 27.1% — well below the 85% threshold — proving the fallback values don't reflect abort-time conditions.

**Fix needed:** Record the actual preflight-time RAM in the metrics entry when the cycle is aborted, rather than (or in addition to) the live fallback value. Options:
1. Add a `preflight_ram_pct` field to the metrics entry when abort occurs, capturing the RAM at the moment preflight failed
2. In `abort_pattern_analyzer.py`, read `preflight_ram_pct` instead of `ram_pct` for abort analysis
3. Add an `abort_ram_pct` field in `run_cycle.py` preflight check that gets stored alongside the live fallback

**Pattern:** Any metrics field that gets filled by a "live fallback" after the triggering event should also record the actual value at the time of the event. Otherwise, analytics tools that compare the fallback value against thresholds will produce incorrect conclusions (e.g., "abort rate is 60% with RAM at 27% — threshold should be lowered" when the actual abort-time RAM was 87%).