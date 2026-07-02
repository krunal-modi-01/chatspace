# Functional Specification — <Feature Name>

> Owner: `business-analyst` agent. Input: PRD. Output consumed by: `architect`, `qa-engineer`.
> Status: Draft | Approved · Traces to PRD: <link>

## 1. Overview
One-paragraph summary of the behavior being specified.

## 2. Actors & roles
Who interacts (users, systems, admins) and their permissions.

## 3. Functional requirements (detailed)
| ID | Traces to (PRD Rn) | Behavior | Preconditions | Postconditions |
|----|--------------------|----------|---------------|----------------|
| F1 | R1 | | | |

## 4. User flows
Step-by-step for each primary flow (numbered). Include alt/exception flows.

```
1. User submits X
2. System validates Y
   2a. If invalid → error Z
3. System persists and confirms
```

## 5. Business rules
Explicit rules/calculations/validations (e.g., limits, eligibility, fees).

## 6. Edge cases & error handling
| Case | Expected behavior |
|------|-------------------|
| Empty/invalid input | |
| Concurrent action | |
| Dependency unavailable | |

## 7. Data dictionary
| Field | Type | Constraints | PII? | Notes |
|-------|------|-------------|------|-------|

## 8. Acceptance criteria (Given/When/Then)
The testable contract for `qa-engineer`.

## 9. Assumptions & dependencies
