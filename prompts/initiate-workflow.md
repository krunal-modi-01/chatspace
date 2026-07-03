Run the `feature-flow` workflow (workflows/feature-flow.workflow.js) to implement
chatspace v1 in dependency-safe batches.

Context you must load first:
- Read docs/spec/chatspace-v1-task-breakdown.md — the 41 tasks (T01–T41), each with a
  "Depends on" line and an owning agent.

Critical constraint: the workflow's pipeline has NO cross-task dependency ordering and
runs each task in its own isolated git worktree, so a task CANNOT see an uncommitted
dependency's code. Therefore drive it in batches:

1. Create and checkout to proper branch, if branch is not the appropriate one.
2. Compute the next batch = every not-yet-committed task whose dependencies are ALL
   already committed on this branch.
3. Invoke the Workflow tool: name 'feature-flow', args { tasks: [...] }, mapping each
   task to { id, kind, desc } where kind ∈ backend|frontend|mobile|infra (from its owner).
4. When it returns, show me each task's code-review verdict + security verdict.
   Do NOT merge or deploy — those are 🔒 human gates.
5. Stop and wait for my approval. On approval, commit the batch, then repeat from step 1
   for the next dependency-safe batch.

Start now with T03 and T08.