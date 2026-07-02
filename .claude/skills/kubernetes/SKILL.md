---
name: kubernetes
description: Invoke when authoring or reviewing Kubernetes manifests/Helm — Deployments, Services, Ingress, resource requests/limits, liveness/readiness/startup probes, HPA, rollout/rollback strategy, security contexts, and Secret handling.
---
# Kubernetes Skill
## Purpose
Deploy and operate workloads on Kubernetes reliably and securely: correctly specified workloads with health probes, resource bounds, autoscaling, safe rollouts, and hardened pods.
## When invoked
- `devops-engineer` writing/reviewing manifests or Helm charts, or handling a rollout/rollback.
- `infrastructure-engineer` designing cluster topology, ingress, or resource policy.
- Debugging a crash-looping, throttled, or unschedulable workload.

## Inputs
- The service to deploy: image, ports, config/secret needs, expected traffic, statefulness.
- Cluster context: available resources, ingress controller, namespaces, existing policies.
- SLA/availability target driving replica count and rollout strategy.

## Outputs
- Manifests/Helm values for Deployment (or StatefulSet/Job), Service, Ingress, HPA, and related objects.
- Probe, resource, and securityContext specifications.
- A rollout/rollback plan.

## Procedure
1. **Pick the right workload object.** Deployment for stateless services; StatefulSet for stable identity/storage (databases, brokers); DaemonSet for per-node agents; Job/CronJob for batch. Do not run stateful data stores as plain Deployments.
2. **Set resource requests and limits** on every container. Requests drive scheduling; limits cap usage. Set CPU/memory requests from observed usage; set memory limit = request (OOM-kill rather than noisy-neighbor). Be cautious with CPU limits — they cause throttling; often set requests only for CPU. Unbounded pods are the top cause of node instability.
3. **Configure all three probes** where relevant:
   - `readinessProbe` — gates traffic; a failing pod is removed from the Service, not killed.
   - `livenessProbe` — restarts a wedged container. Keep it cheap and independent of dependencies (or it cascades restarts).
   - `startupProbe` — protects slow-starting apps from premature liveness kills.
4. **Expose via Service + Ingress.** ClusterIP for internal; Service fronts pods by label selector. Ingress (or Gateway API) for external HTTP(S) with TLS termination and host/path routing. Avoid `type: LoadBalancer` per service when an Ingress can consolidate.
5. **Autoscale with HPA** on a meaningful signal (CPU/memory or custom/external metrics). Set sensible min/max replicas; ensure requests are set (HPA needs them). Consider PodDisruptionBudgets so scaling/drains don't drop below availability floor.
6. **Choose a rollout strategy.** Default RollingUpdate with tuned `maxSurge`/`maxUnavailable`. For risky changes use blue/green or canary (via a progressive-delivery controller). Always keep readiness probes accurate so rollout waits for real readiness. Roll back with `kubectl rollout undo` and keep `revisionHistoryLimit` sane.
7. **Harden the pod securityContext:** `runAsNonRoot: true`, drop all capabilities, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, no `privileged`. Apply a restricted Pod Security admission level. Scope RBAC to the workload's ServiceAccount with least privilege.
8. **Handle Secrets correctly.** Mount Secrets as files or env from `Secret` objects; never bake secrets into images or ConfigMaps. Note plain `Secret` objects are only base64, not encrypted — enable encryption-at-rest and/or use an external secrets operator (External Secrets, Vault) for real protection.

## Best practices
- Pin image tags to digests or immutable versions; never `:latest` in prod.
- Namespaces per team/env with ResourceQuotas and LimitRanges.
- NetworkPolicies to default-deny and allow only needed traffic.
- Liveness probes must not depend on downstream services.
- Use PodDisruptionBudgets + topology spread for real availability, not just replica count.

## Anti-patterns
- No resource requests/limits, or memory limit far above request (invites OOM chaos).
- `livenessProbe` that hits a database — one dependency blip restarts every pod.
- Running as root / privileged containers by default.
- Secrets in ConfigMaps, images, or committed manifests.
- `:latest` image tags making rollbacks non-deterministic.
- HPA configured without resource requests (it won't scale).

## Files included
- `SKILL.md` — this file.
