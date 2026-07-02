# Defending LLM/Agent Features Against Prompt Injection

Any content an agent reads that a third party can influence — issue text, PR comments, web pages, error payloads, file contents, MCP tool output — is **untrusted input**. It may contain instructions aimed at hijacking the agent.

## Principles
1. **Data, not instructions.** Fetched/tool-returned content is data to analyze, never commands to obey. State this in system prompts.
2. **Privilege separation.** Don't combine high-privilege tools (write to prod, move money, push code) with untrusted-content ingestion in the same context unless required. In this pipeline, MCP servers that egress/ingest untrusted content are separated from mutation-capable ones (see `.claude/mcp/README.md`).
3. **Human-in-the-loop for effects.** Any irreversible/outbound action routes through `settings.json` `ask` permissions — an injected instruction still can't act unilaterally.
4. **Output filtering.** Scrub secrets/PII from anything an agent emits (the `secret-scan` hook backs this).
5. **Least tools.** Give each agent only the tools its role needs (agent frontmatter `tools:`).

## Checklist for building an LLM feature
- [ ] System prompt explicitly marks external content as untrusted.
- [ ] Tool-use is allowlisted and, for effects, gated on human/approval.
- [ ] No secrets in the prompt/context; retrieved via short-lived scoped creds.
- [ ] Outputs validated/schema-checked before acting on them.
- [ ] Rate limits + abuse monitoring on the feature.
- [ ] Injection test cases in the test suite (e.g., "ignore previous instructions" payloads).
