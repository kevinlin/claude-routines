# Decision: retire Flow Fabric

| | |
|---|---|
| Status | Decided |
| Date | 2026-11-15 |
| Owner | Kevin Lin |
| Supersedes | [direction_flow-fabric.md](direction_flow-fabric.md), [prd_v2_factory-intake.md](prd_v2_factory-intake.md) |

## Decision

- Flow Fabric stops as a product. No further work on the engine, the web UI, M5 or the v2 factory intake.
- Personal recurring work moves to routines: markdown files in `~/routines`, run by Claude Desktop local scheduled tasks through one `routine` skill.
- The code in this repo stays as it is. Nothing is deleted.

## Why

- **It never ran a real workflow.** Four months after M4 there was no data dir, the launchd unit was not installed, the soak log in [soak-runbook.md](../ops/soak-runbook.md) was empty, and the flagship `rfp-daily-routine.bpmn` had never been refined into a deployable definition.
- **The first automation cost hours.** A workflow needed a BPMN drawn elsewhere, an upload, a grill session per node, a prompt, a JSON Schema and a JavaScript condition per node, a lint pass and a dry run. The `rfp-daily` skill does the same job in 195 lines of markdown.
- **Agent tasks could not use my setup.** `AgentRunner` runs with `settingSources: []`: no skills, no MCP servers, no CLAUDE.md. Each node was a fresh session that knew only its typed inputs.
- **Nothing started by itself.** Start was manual. Recurrence was a timer loop inside one instance that stayed open for days.
- **A run produced engine state.** Variables, a token overlay and a timeline, but no summary of what was found.
- **Plain prompt + cron already worked.** Over the same period two cowork-z automations, each a few lines of prompt calling a skill, completed 58 runs.
- **The v2 plan added plumbing.** A queue, a scheduler, chaining and typed inputs would still have left zero real workflows running.

The underlying mistake was BPMN-first authoring. It demands a complete formal model before the first useful run, which is the opposite of "do it by hand first, keep it simple" from the notes this project started from ([forget-loop-engineering-indydevdan.md](forget-loop-engineering-indydevdan.md)).

## What replaces it

- **Skills** stay the home for common capabilities: reviewing a Vertec month, recapping a meeting, the RFP daily check.
- **Routines** are personal: one person's data, timing and decisions. A routine names the skills to call, the points where it must ask first, and what "done" means.
- **Claude Desktop local scheduled tasks** fire them. Each task holds only the prompt `/routine run <name>`.
- **A watchdog script** on launchd flags failed, stalled, overdue and waiting routines twice a day, without Claude.

Options that were considered and dropped: routines stamped onto the existing BPMN engine, and extending cowork-z automations. Both mean maintaining an app for something the platform now does.

## What carried over from Flow Fabric

- **Never silently stall.** Every run writes a record before it starts work and ends as `done`, `needs-you` or `failed`. A deterministic check outside the agent reads those records.
- **The human gate.** A run stops at each action that changes something in my name, waits for a yes, and resumes. An unanswered question survives in the run record.
- **Deterministic code around the agent.** The health check contains no model call.
- **State outside the conversation.** Memory and run history are files, so a run needs no earlier session.

## What was given up

- Engine-owned control flow. Inside a routine the agent decides the order of steps; only the ask-before gates and the run record are fixed.
- Durable timers and resume after a crash mid-run. A crashed run is flagged and started again; it does not continue from the failed step.
- The BPMN import and refinement story for client demos.
- Per-step cost and timing, the live diagram, dashboards and OTel export.

## This repo

- Kept as a record. M1 to M4 remain built and tested; see [CLAUDE.md](../../CLAUDE.md).
- M5 (soak and acceptance) and all v2 milestones are cancelled; see [the spec index](../specs/index.md).
- The GitHub repository was archived on 2026-11-15. Issue #1, which tracked the v2 factory intake, had already been deleted.
