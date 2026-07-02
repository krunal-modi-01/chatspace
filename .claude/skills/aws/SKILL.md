---
name: aws
description: Invoke when provisioning, reviewing, or reasoning about AWS infrastructure — choosing compute/storage/network services, applying IAM least-privilege, estimating or reducing cost, or introspecting live account state read-only. Analogous guidance applies to Azure and GCP.
---
# AWS Skill
## Purpose
Apply AWS Well-Architected essentials so infrastructure decisions are secure, cost-aware, and operationally sound. Provide a consistent way to introspect live account state read-only before making recommendations.
## When invoked
- `infrastructure-engineer` designing or reviewing an AWS topology (VPC, compute tier, data stores).
- `devops-engineer` wiring CI/CD to AWS, setting up deploy targets, or debugging a running service.
- Any request to "pick a service for X", tighten IAM, or explain/reduce a bill.
- Reviewing Terraform/CloudFormation whose resources land in AWS (pairs with the `terraform` skill).

Note: the reasoning here is cloud-agnostic. Substitute Azure (Entra ID, Resource Groups, VNets) or GCP (IAM, Projects, VPCs) equivalents when the target is not AWS.

## Inputs
- Workload description: traffic shape, statefulness, latency/SLA, data sensitivity, region/residency constraints.
- Existing account context: account/org structure, existing VPCs, tagging conventions, budget.
- Read-only access to a cloud MCP or `aws` CLI with a read-only role for introspection.

## Outputs
- A service-selection recommendation with rationale and at least one rejected alternative.
- IAM policy (least-privilege JSON) or a gap list against existing policies.
- Cost estimate or cost-reduction findings with the pricing dimensions that drive them.
- Optionally, an inventory of current-state resources relevant to the decision.

## Procedure
1. **Clarify the workload first.** Do not name a service until you know: stateless vs stateful, request/sec and burstiness, sync vs async, data durability/residency needs, and the SLA. Under-specification is the most common cause of wrong picks.
2. **Introspect current state (read-only).** Before proposing changes, inventory what exists via the cloud MCP or CLI. Never run mutating commands here.
   - Identity/region: `aws sts get-caller-identity`, `aws configure list`.
   - Networking: `aws ec2 describe-vpcs`, `describe-subnets`, `describe-security-groups`.
   - Compute/data: `describe-instances`, `ecs list-services`, `rds describe-db-instances`, `s3api list-buckets`.
   - IAM surface: `aws iam list-roles`, `get-account-authorization-details` (read-only).
3. **Choose compute** by ownership vs control trade-off. Prefer the most managed option that meets the constraint:

   | Need | Prefer | Avoid unless |
   | --- | --- | --- |
   | Event/glue, spiky, <15 min | Lambda | steady high throughput (cost) |
   | Containerized service, no node mgmt | ECS Fargate | you need custom kernels/GPUs |
   | Full control, GPU, daemonsets | EKS / EC2 | a managed option fits (ops cost) |
   | Managed web app | App Runner / Elastic Beanstalk | you need fine networking control |

4. **Choose storage/data** by access pattern: S3 for objects/blobs and static assets; RDS/Aurora for relational with transactions; DynamoDB for key-value at scale with predictable access; ElastiCache for hot reads; EBS only for instance-attached block storage. Match S3 storage class (Standard → IA → Glacier) to access frequency.
5. **Design the network** with least exposure: private subnets for compute and data, public subnets only for load balancers/NAT. Security groups reference other security groups, not `0.0.0.0/0`, except on public LBs. Use VPC endpoints for S3/DynamoDB to keep traffic off the internet.
6. **Apply IAM least-privilege.** Start from deny-all; grant the minimum actions on the minimum resources. Use roles (never long-lived access keys) for workloads; scope with conditions (source VPC, tags, MFA). Prefer managed policies only when they are genuinely least-privilege; otherwise write scoped inline/customer-managed policies.
7. **Estimate cost** by the dimensions that actually bill: compute-hours/invocations, data transfer *out* and cross-AZ, storage GB-month + request counts, NAT gateway hours. Flag the top 2-3 cost drivers explicitly and note commitment options (Savings Plans, reserved) only for steady baseline load.
8. **Check against the Well-Architected pillars** — operational excellence, security, reliability, performance efficiency, cost optimization, sustainability — and name any pillar the design trades away.

## Best practices
- Tag everything (owner, env, cost-center) — cost allocation and cleanup depend on it.
- Use roles + STS/short-lived credentials; rotate and audit. Never embed access keys in code or state.
- Multi-AZ for anything with an availability SLA; multi-region only when the requirement justifies the cost/complexity.
- Encrypt at rest (KMS) and in transit by default; enable it at creation, not retrofit.
- Put a budget alarm on any new account or major workload before it grows.

## Anti-patterns
- Naming a service before the workload's shape is known.
- `Action: "*"` / `Resource: "*"` IAM policies, or `0.0.0.0/0` ingress on non-LB resources.
- Long-lived IAM user access keys for workloads or CI.
- Public S3 buckets by default; block public access at the account level.
- Ignoring cross-AZ and egress data-transfer costs in estimates.
- Running mutating CLI/MCP calls during a read-only introspection.

## Files included
- `SKILL.md` — this file.
