export const meta = {
  name: 'feature-flow',
  description: 'Orchestrate a feature from frozen spec to verified, review-ready change with adversarial verification',
  phases: [
    { title: 'Design' },
    { title: 'Implement' },
    { title: 'Review' },
    { title: 'Verify' },
  ],
}

// `args` = {
//   specLink,                       // technical spec path
//   contractDoc, dbDesignDoc,       // frozen, human-approved specs (optional overrides)
//   tasks: [{ id, kind: 'backend'|'frontend'|'mobile'|'infra', desc }]
// }
// This script prepares a change for the 🔒 human review + deploy gates. It NEVER merges or deploys.

const specLink = args?.specLink ?? 'docs/spec/chatspace-v1-technical-spec.md'
const contractDoc = args?.contractDoc ?? 'docs/spec/chatspace-v1-api-contract.md'
const dbDesignDoc = args?.dbDesignDoc ?? 'docs/spec/chatspace-v1-database-design.md'
const tasks = args?.tasks ?? []

// Map task kind → canonical roster agent (see CLAUDE.md AGENT ROSTER).
const ENGINEER = {
  backend: 'backend-engineer',
  frontend: 'frontend-engineer',
  mobile: 'mobile-engineer',
  infra: 'infrastructure-engineer',
}

const taskList = tasks.map((t) => `- ${t.id} (${t.kind}): ${t.desc}`).join('\n')

// ── Design: extract the relevant slice from the FROZEN specs (do not re-derive) ──
phase('Design')
const [contract, dataModel] = await Promise.all([
  agent(
    `The frozen, human-approved API contract lives at ${contractDoc}. Do NOT redesign it. Read it and return — verbatim where possible — only the endpoints, request/response schemas, and error shapes relevant to these tasks:\n${taskList}`,
    { label: 'design:api', phase: 'Design', agentType: 'api-reviewer' }
  ),
  agent(
    `The frozen, human-approved database design lives at ${dbDesignDoc}. Do NOT redesign it. Read it and return the tables, columns, enums, indexes, constraints, and any migration notes relevant to these tasks:\n${taskList}`,
    { label: 'design:db', phase: 'Design', agentType: 'database-engineer' }
  ),
])

// ── Implement → Review → fix, pipelined per task (no batch barrier) ──
const results = await pipeline(
  tasks,
  // Stage 1: implement (isolated worktree so parallel tasks don't collide)
  (t) => agent(
    `Implement task ${t.id} — "${t.desc}" — per technical spec ${specLink}.\n` +
      `Conform EXACTLY to this frozen API contract slice:\n${contract}\n` +
      `and this frozen data model slice:\n${dataModel}\n` +
      `Write code + tests; run lint/typecheck/tests until green. Honor CLAUDE.md conventions, boundaries, and security requirements.`,
    { label: `impl:${t.id}`, phase: 'Implement', isolation: 'worktree', agentType: ENGINEER[t.kind] ?? 'backend-engineer' }
  ),
  // Stage 2: review the produced change
  (impl, t) => agent(
    `Review the change for task ${t.id} — "${t.desc}". Return findings as file:line · severity · concrete failure scenario · fix. Verdict: approve/request-changes.`,
    { label: `review:${t.id}`, phase: 'Review', agentType: 'code-reviewer' }
  ).then((review) => ({ task: t, impl, review })),
)

// ── Verify: security + a concrete-failure check, per task, in parallel ──
phase('Verify')
const verified = await parallel(results.filter(Boolean).map((r) => () =>
  agent(
    `Adversarially verify the change for task ${r.task.id} — "${r.task.desc}". Apply the security skill checklist (auth/input/secrets/IDOR/PII). Report any HIGH/CRITICAL with an exploit path, else 'clean'.`,
    { label: `verify:${r.task.id}`, phase: 'Verify', agentType: 'security-reviewer' }
  ).then((security) => ({ ...r, security }))
))

return {
  contract, dataModel,
  tasks: verified.filter(Boolean),
  note: 'Prepared for 🔒 human review + deploy gates. No merge/deploy performed.',
}
