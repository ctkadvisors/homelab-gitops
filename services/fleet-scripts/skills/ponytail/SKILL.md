---
name: ponytail
description: How to make a change as small as it can be and still work. Load it before your first edit on any implement or fix task; it keeps a mid-sized task from growing into a rewrite.
homepage: https://github.com/DietrichGebert/ponytail
license: MIT (Dietrich Gebert, 2026; trimmed for the fleet)
---
# Ponytail: the lazy senior developer

Lazy means efficient, not careless. The best code is the code never written.

## The ladder (stop at the first rung that holds)

1. **Does this need to exist at all?** Speculative need = skip it, say so in one line.
2. **Already in this codebase?** A helper, type or pattern that already lives here: reuse it. Look before you write.
3. **Stdlib does it?** Use it.
4. **The platform does it?** A DB constraint over app code, CSS over JS, a k8s field over a script.
5. **An installed dependency does it?** Use it. Never add a new one for what a few lines can do.
6. **Can it be one line?** One line.
7. **Only then:** the minimum code that works.

The ladder runs *after* you understand the problem, never instead of it. Read the task and the
code it touches, trace the real flow end to end, then climb.

**Bug fix = root cause, not symptom.** Before you edit, grep every caller of the function you are
about to touch. One guard in the shared function is a smaller diff than a guard in every caller,
and patching only the path the report names leaves every sibling still broken.

## Rules

- No unrequested abstractions: no interface with one implementation, no config for a value that never changes.
- No scaffolding "for later". Deletion over addition. Boring over clever.
- Fewest files possible. Shortest working diff wins, once you understand the problem. The smallest
  change in the wrong place is a second bug.
- A deliberate corner with a known ceiling gets a `# ponytail:` comment naming the ceiling and the upgrade path.
- Big request? Ship the lazy version and say in one line what you left out and when it would be needed.

## Output

Code first. Then at most three short lines: what was skipped, when to add it. If the explanation
is longer than the code, delete the explanation.

## When NOT to be lazy

Never simplify away input validation at a trust boundary, error handling that prevents data loss,
security, or anything the brief explicitly asks for. Never lazy about reading: a small diff shipped
without understanding is a confident wrong fix.

Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the
smallest thing that fails if the logic breaks (that is what verify.sh is for). Trivial one-liners
need no test.

The shortest path to done is the right path.
