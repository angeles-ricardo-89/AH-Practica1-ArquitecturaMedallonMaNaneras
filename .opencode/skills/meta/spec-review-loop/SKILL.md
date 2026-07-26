---
name: spec-review-loop
description: Analyze a design spec for ambiguities and contradictions after brainstorming. Loop back to brainstorming + socratic-method if issues found (max 3 iterations). Escalate to PO if stuck.
location: .opencode/skills/meta/spec-review-loop/SKILL.md
---

# Spec Review Loop — Post-Brainstorming Quality Gate

## Purpose

After brainstorming produces a design spec, this skill scans the spec for ambiguities and contradictions before the agent transitions to writing-plans. If issues are found, it triggers a re-brainstorming loop (max 3 iterations). If the 3rd iteration still has unresolved issues, the agent MUST escalate to the PO and block further progress.

## When to Use

- Immediately after brainstorming produces a spec (before invoking writing-plans)
- After each re-brainstorming iteration (to re-check the revised spec)

## Procedure

### 1. Read the spec

Read the entire spec file. Do not skim.

### 2. Ambiguity scan

Search for:

| Pattern | Example |
|---|---|
| Undefined terms | "the system should be fast" (what does fast mean?) |
| Vague scope | "handle errors" (which errors? how?) |
| TBD / TODO / placeholders | "TBD: error handling strategy" |
| Unquantified acceptance criteria | "it should work well", "must be responsive" |
| Open-ended verbs without boundaries | "support", "manage", "handle" without specifying what |

### 3. Contradiction scan

Compare sections for conflicts:

| Pattern | Example |
|---|---|
| Architecture vs. component list | Diagram shows 4 services, component list describes 3 |
| Data flow direction conflict | Section A says "API pushes to worker", Section B says "worker polls API" |
| Constraint vs. approach | "Must be synchronous" but design uses async queue |
| Scope statement vs. included features | "MVP: login only" but spec includes registration |

### 4. Report findings

Output a structured report:

```
## Spec Review: <spec-path>

### Iteration: <1/2/3>

### Ambiguities Found
- [ ] <description> — location: <section/line>

### Contradictions Found
- [ ] <description> — <section A> vs <section B>

### Decision
- 0 issues → PASS. Proceed to writing-plans.
- Issues found + iter < 3 → RETRY. Invoke socratic-method + brainstorming with findings.
- Issues found + iter = 3 → ESCALATE to PO. GATE-S BLOCKS.
```

### 5. If RETRY

1. Announce: "Spec has <N> issues. Re-entering brainstorming loop (iteration <current>/3)."
2. Invoke socratic-method skill with the findings as questions to explore
3. Invoke brainstorming skill to produce a revised spec incorporating the fixes
4. Re-run this spec-review-loop with incremented iteration counter

### 6. If ESCALATE

1. Announce: "GATE-S BLOCKED. Spec has unresolved issues after 3 iterations."
2. Present the accumulated findings to the PO
3. Do NOT invoke writing-plans or any implementation skill

## Integration

- Called from AGENTS.md R2.5.1
- Enforced by GATE-S-SPEC-QUALITY.md exit criteria
- Feeds into brainstorming (for retry) or writing-plans (for pass)

## Reference

- GATE: `governance/GATE-S-SPEC-QUALITY.md`
- Policy: `AGENTS.md` R2.5.1, R2.5.2
