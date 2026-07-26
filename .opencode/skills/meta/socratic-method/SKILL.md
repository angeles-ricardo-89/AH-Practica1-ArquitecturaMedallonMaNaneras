---
name: socratic-method
description: Applies the Socratic Method to software engineering tasks — question assumptions, elicit requirements through dialogue, surface hidden complexity, and validate understanding before implementing. Use before any creative or design work.
---

# Socratic Method for Code Agents

## Purpose

Apply disciplined questioning to software engineering tasks. The Socratic Method exposes assumptions, clarifies intent, discovers edge cases, and reveals hidden complexity *before* writing code. It is the antidote to premature implementation and shallow understanding.

## Core Principles

### 1. Never Assume — Always Inquire
The agent's first response to any request is not action, but understanding. Hidden context matters more than visible requirements.

### 2. Question the Question
"Why is this needed?" precedes "How do I build it?" Every feature request contains an unstated problem. Find it.

### 3. Surface Tradeoffs Explicitly
Every design decision has costs. The agent's role is to make them visible so the human can choose consciously.

### 4. Explore Boundaries Before Center
Edge cases define the shape of the solution. Happy-path thinking produces fragile systems.

### 5. Validate Mutually
Understanding is verified through restatement, not assumption. "I understand X, is that correct?"

## The Method — Five Dialogic Moves

### Move 1: Clarify Intent
Before anything else, restate the goal in your own words and confirm alignment.

**Agent prompt:** "Let me restate what I understand: you need [X] because [Y]. The constraint is [Z]. Is that accurate?"

**Red flags this catches:** Ambiguous scope, mismatched expectations, XY problems.

### Move 2: Explore Constraints
Every requirement lives within boundaries. Ask about them explicitly.

**Agent prompt:** "What are the constraints here? For example: time budget, compatibility requirements, performance expectations, team conventions, or regulatory needs?"

**Red flags this catches:** Hidden non-functional requirements, implicit assumptions about scale or audience.

### Move 3: Surface Alternatives
For any proposed solution, ask: "What else could work?" Force comparison.

**Agent prompt:** "The approach you're suggesting is [A]. Another way to achieve the same goal would be [B], which trades off [X] for [Y]. Which tradeoff matters more to you?"

**Red flags this catches:** Local-optimum thinking, path dependence, sunk-cost justification.

### Move 4: Test with Counterexamples
Probe the proposal with scenarios that break it. Engineering is about what happens when things go wrong.

**Agent prompt:** "How should the system behave if [unexpected condition]? For example: missing data, concurrent writes, network failure, or user error?"

**Red flags this catches:** Missing error handling, optimistic assumptions, undefined failure modes.

### Move 5: Establish Success Criteria
"A solution exists when..." must be explicit before work begins.

**Agent prompt:** "How will we know this is done correctly? What specific behaviors, outputs, or test cases define success?"

**Red flags this catches:** Unbounded scope, subjective "done" definitions, untestable outcomes.

## When to Apply

### Always apply (mandatory):
- Before any implementation plan or design work
- When receiving a multi-paragraph or ambiguous request
- When asked to modify behavior or add features
- When the request contains "just", "simply", or "obviously"

### Often apply (discretionary):
- When estimating effort or complexity
- When choosing between frameworks or approaches
- When reviewing code or architecture

### Skip (anti-pattern):
- Trivial, well-defined tasks (e.g., "rename X to Y across the project")
- The answer is objectively a single command or edit
- Emergency fixes where the fix is obvious and the context is clear

## Anti-Patterns

- **Performing the method silently** — The dialog must be visible. The human cannot see your internal reasoning.
- **Leading questions** — "Don't you think X is better?" is not inquiry; it's advocacy disguised as curiosity.
- **Analysis paralysis** — The method serves action, not delay. Two rounds of questioning is usually sufficient.
- **Asking questions with obvious answers** — If the answer is trivially derivable from the codebase, don't ask. Read the code.
- **Philosophical tangents** — Stay grounded in the engineering reality. "But what is a file, really?" is not productive.

## Example Dialogues

### Example 1: Feature Request (Good)

**Human:** "Add dark mode to the dashboard."

**Agent:** "I see three aspects to consider. First, should dark mode be user-toggleable, follow the OS preference, or both? Second, do we need to adapt chart colors and data visualizations, or is this just the chrome? Third, have you chosen a color palette, or should I derive one from your brand colors?"

**Why this works:** The agent exposed three ambiguous dimensions (trigger, scope, palette) with concrete options, each pointing to different implementation costs.

### Example 2: Feature Request (Bad)

**Human:** "Add dark mode to the dashboard."

**Agent:** "I'll add a theme toggle to the settings panel and create a dark CSS theme. Starting implementation now."

**Why this fails:** The agent assumed scope (full dashboard vs. chrome only), trigger mechanism (toggle vs. auto), and palette without validation.

### Example 3: Bug Report (Good)

**Human:** "The upload fails for large files."

**Agent:** "Two questions: what size triggers the failure, and what error do you see? I'd also want to check whether this is a timeout (client gives up waiting), a memory issue (server runs out of RAM buffering), or a validation rejection (file too large rule). Which layer do you suspect?"

**Why this works:** The agent decomposed "fails" into distinct root-cause categories, each requiring different fixes, and asked for evidence to narrow them down.

## Integration with Other Skills

- **brainstorming** → Apply the Socratic Method *during* brainstorming, not instead of it
- **writing-plans** → Socratic questioning should precede and inform the plan
- **systematic-debugging** → Socratic Method forms the hypothesis-generation phase
- **test-driven-development** → Counterexample exploration feeds test case design

## Verification

After applying the Socratic Method, confirm:
1. The human has explicitly agreed with your understanding
2. Edge cases and constraints are documented (at least mentally)
3. Alternative approaches have been considered and dismissed for reasons
4. Success criteria are specific enough to test against
