# Internal Auditor — how it all connects

A one-page map of the runtime, in plain terms. Think of the system as a
**compliance audit firm**: a client phones the front desk with an audit
request and waits on the line; the lead auditor dispatches two junior
specialists; each specialist signs out a private sealed booth to pull
data; the lead assembles the report and reads it back on the same call.

## Runtime flow

```mermaid
flowchart TD
    sched["Cloud Scheduler (cron)"] -->|"POST /audit"| svc
    caller["ad-hoc / other agents"] -->|"POST /audit"| svc

    subgraph default["namespace: default"]
        svc["ClusterIP Service<br/>internal-auditor:8080"] --> orch["Orchestrator pod (FastAPI)<br/>Gemini Pro — the lead auditor"]
    end

    orch -->|"tool call (parallel)"| la["log_analyzer<br/>Gemini Flash"]
    orch -->|"tool call (parallel)"| as["asset_inspector<br/>Gemini Flash"]

    subgraph agentsandbox["namespace: agent-sandbox"]
        wp1["SandboxWarmPool<br/>gcp-log-analyzer-warmpool-mcp<br/>(idle gVisor pods)"]
        wp2["SandboxWarmPool<br/>gcp-cloud-asset-warmpool-mcp<br/>(idle gVisor pods)"]
        pod1["claimed pod<br/>gcp-log-analyzer MCP server"]
        pod2["claimed pod<br/>gcp-cloud-asset MCP server"]
        wp1 -. "SandboxClaim binds one" .-> pod1
        wp2 -. "SandboxClaim binds one" .-> pod2
    end

    la -->|"claim → talk MCP → release"| pod1
    as -->|"claim → talk MCP → release"| pod2

    pod1 -->|"Workload Identity"| gcp
    pod2 -->|"Workload Identity"| gcp
    gcp["GCP APIs<br/>Cloud Logging · Cloud Asset"]

    la -->|"findings"| orch
    as -->|"findings"| orch
    orch -->|"merged report {run_id, ...}"| svc
    svc -->|"HTTP 200 response"| caller
```

## How one "booth sign-out" works (Model A: per-call claim)

```mermaid
sequenceDiagram
    participant S as Specialist (Flash)
    participant C as common/sandbox.py
    participant K as Agent Sandbox controller
    participant P as Warm-pool pod (MCP server)

    S->>C: need the log-analyzer MCP endpoint
    C->>K: create SandboxClaim (warmpool = ...-warmpool-mcp)
    K->>P: bind an idle pod, write podIP to claim status
    C-->>S: http://<podIP>:8080/mcp
    S->>P: call MCP tool (e.g. query logs) — direct to pod IP
    P->>P: query GCP via Workload Identity
    P-->>S: raw results (no judgement)
    C->>K: delete SandboxClaim (release)
    K->>P: recycle pod back into the pool
```

The claim is created and deleted **once per tool call**. Note the two
network layers: the *outer* trigger is an HTTP request to the
orchestrator (`POST /audit`), but the *inner* specialist→MCP hop routes
through **no Service** — the specialist talks straight to the claimed
pod's IP, then hands it back.

## The translation table

| Audit-firm analogy | Real component |
| --- | --- |
| The recurring 9am call / an ad-hoc caller | Cloud Scheduler cron, or an agent/human hitting `POST /audit` |
| The **front desk phone line** | the **ClusterIP Service** (`internal-auditor:8080`) |
| **Lead auditor** answering the phone, reports back on the same call | the **orchestrator pod** — a **FastAPI** service (synchronous) |
| The lead's experienced brain | **Gemini Pro** (orchestrator model) |
| Two **junior specialists** | `log_analyzer` + `asset_inspector` tools |
| The juniors' faster, cheaper brains | **Gemini Flash** (specialist model) |
| The **room of idle, pre-set-up booths** | the **warm pool** (`SandboxWarmPool`) |
| **Signing out a booth** for one task | a **SandboxClaim** (`common/sandbox.py`) |
| The booth being **sealed** | **gVisor** sandbox isolation |
| The terminal in the booth | the **MCP server** in the claimed pod |
| The terminal's **ID badge** | **Workload Identity** → GSA with read access |
| The **government archive** | **GCP** APIs (Cloud Logging, Cloud Asset) |
| **Signing the booth back in**, cleaner resets it | releasing the claim → pod recycled/replenished |
| The **report read back on the call** | the merged JSON in the HTTP response (keyed by `run_id`) |
| **Facilities/HR** who set up the lead's office | your team's **Terraform** (deploys the orchestrator) |
| The company that **built the booth room** | whoever **deployed the warm pools** |

## Two things this design deliberately does

- **Model A (per-call claim), not a shared Service for MCP.** Every tool
  call gets its own private, sealed, throwaway pod, then returns it. More
  isolation per task; the cost is the claim machinery in `sandbox.py`.
- **Synchronous HTTP, in-cluster only.** `POST /audit` runs the audit and
  returns the merged JSON in the response — so cron, ad-hoc callers, and
  other agents all get the result directly. It's exposed as a ClusterIP
  Service (no external load balancer in the path), so there's no LB
  timeout to truncate a long audit; clients just set a generous timeout.

## Who owns what (deployment)

| Owned by this repo | Owned outside this repo |
| --- | --- |
| Agent code + container image | Orchestrator Deployment (Terraform) |
| GCP setup (BQ/Firestore for the future Policy Agent) | ServiceAccount + Workload Identity (Terraform) |
| The runtime env contract (`SANDBOX_*`, warm-pool names, Vertex vars) | ClusterIP Service (Terraform) |
| — | Cross-namespace SandboxClaim RBAC (Terraform) |
| — | MCP servers + their warm pools (separate) |
