# Paste this as the first message of the next session

```
Continue the Berkeley Waitlist Odds project. The repo is at /Users/oliverguo/berkeley-waitlist-odds
(public: https://github.com/oliver139-chinesemole/berkeley-waitlist-odds; the origin remote uses the
SSH alias github-chinesemole, and gh is logged in as oliver139-chinesemole).

Before doing anything:
1. Read docs/dev/HANDOFF.md (what is done, what is left, how to resume, decisions not to undo).
2. Read CLAUDE.md in the repo (the "Current step" line and the repo rules) and the tracker at the
   bottom of docs/dev/FINISH_PLAN_WAITLIST.md.
3. Run the resume commands from HANDOFF.md: activate .venv, pull main, pull ./data-branch, run the
   gap report for the last 24 hours, list the recent scrape runs.

Then do the first item under "What is left" that is due today, and keep going through the plan.
Rules: never commit to the data branch by hand; only analysis.yml commits to main; keep every
number in CLAIMS.md measured, never typed; log outages and switches in docs/DATA_LOG.md; the
site never shows simulated numbers.
```

Key files, for orientation:

| Purpose | File |
| --- | --- |
| Everything done and left, resume commands | docs/dev/HANDOFF.md |
| Repo rules and current step | CLAUDE.md |
| Roadmap with checkboxes and status tracker | docs/dev/FINISH_PLAN_WAITLIST.md |
| Data-route evidence and Spring 2027 dates | docs/PHASE0.md |
| Scraper contract (sections 11 to 15 override earlier ones) | docs/DESIGN_A2.md |
| Flow reconstruction, survival analysis, site contracts | docs/DESIGN_A4.md, docs/DESIGN_A5.md, docs/DESIGN_A6.md |
| Assumptions with validation numbers | docs/ASSUMPTIONS.md |
| How runs work, what to do when one fails, Sunday check, site refresh | docs/RUNBOOK.md |
| Outages, switches, decisions with UTC times (censoring rules) | docs/DATA_LOG.md |
| Resume claims with check commands and measured results | CLAIMS.md |
| Persistent memory for Claude Code | ~/.claude/projects/-Users-oliverguo/memory/project_berkeley_waitlist_odds.md |
