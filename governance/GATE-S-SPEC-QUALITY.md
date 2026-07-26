# GATE-S: Spec & Plan Quality

**Status:** PERPETUO (siempre activo)
**Type:** Manual verification (agent-enforced)
**Enforcement:** Agent workflow — AGENTS.md

## Purpose

GATE-S garantiza que ninguna especificacion ambigua o plan incompleto avance a implementacion. Bloquea la transicion brainstorming→plans y plans→implementacion si los criterios de calidad no se cumplen.

## Exit Criteria

### Spec Quality (must pass before transitioning brainstorming → writing-plans)

- [ ] Spec analyzed with `.opencode/skills/meta/spec-review-loop/SKILL.md`
- [ ] Zero unresolved ambiguities: all terms defined, scope explicit, no TBD/TODO/placeholders
- [ ] Zero internal contradictions: no section contradicts another
- [ ] Iteration counter for this spec ≤ 3; if iteration = 3 and issues remain → PO escalation, GATE BLOCKS
- [ ] Spec committed to `docs/superpowers/specs/`

### Plan Quality (must pass before transitioning plans → implementation)

- [ ] Plan explicitly references the design spec: path + commit hash in header
- [ ] Plan contains "Onboarding" section covering only the domains affected by the plan
- [ ] All checkpoints are atomic: each task touches ≤5 files; tasks with >5 files have a self-explanatory subspec
- [ ] Plan explicitly states edge case coverage: "## Edge Case Coverage" section with bullet list
- [ ] Plan is self-contained: can be executed by an agent receiving only `ejecuta el plan <plan>.md`

## Verification

GATE-S is qualitative and agent-enforced. No auto-check script exists. The agent verifies compliance by:

1. Running the spec-review-loop checklist on the spec before invoking writing-plans
2. Checking the plan header and sections against the Plan Quality criteria before starting implementation

## Related

- `AGENTS.md`
- `.opencode/skills/meta/spec-review-loop/SKILL.md`

