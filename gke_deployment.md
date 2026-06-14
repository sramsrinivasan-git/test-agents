# GKE Agent Sandbox Infrastructure Setup

## Overview

This document provides the complete, end-to-end instructions for provisioning a secure Google Kubernetes Engine cluster tailored for the Agent Sandbox. It includes the necessary enterprise compliance flags, dedicated node pools, and custom resource definitions required to securely execute untrusted Model Context Protocol server workloads.

## Phase 1: Environment Setup and API Activation

Before executing any cloud infrastructure commands, you must establish your core configuration variables and activate the foundational Google Cloud services. You can copy the initial initialization block to define your targeted project ID, choose your deployment zone, and name your cluster resources. Once these variables are set in your terminal session, you must enable both the Kubernetes Engine API and the Artifact Registry API to allow the allocation of the underlying resources. Running this integrated setup block ensures these backends are fully active and initialized before any compute infrastructure attempts to spin up.

```bash
export PROJECT_ID=$(gcloud config get project)
export CLUSTER_NAME="agent-sandbox-cluster"
export LOCATION="us-central1-a"
export NODE_POOL_NAME="agent-sandbox-node-pool"

gcloud services enable container.googleapis.com artifactregistry.googleapis.com --project=${PROJECT_ID}
```

## Phase 2: Provisioning the Secure Private GKE Cluster
If your Google Cloud project retains the standard default network infrastructure, you can deploy your cluster without specifying additional network routing flags. This approach automatically attaches your new nodes to the default Virtual Private Cloud network and its corresponding regional subnetwork. You will simply execute the standard command below to provision your Secure Private GKE cluster using Dataplane v2 and shielded nodes.

```bash
gcloud beta container clusters create ${CLUSTER_NAME} \
  --project=${PROJECT_ID} \
  --location=${LOCATION} \
  --num-nodes=2 \
  --enable-ip-alias \
  --enable-private-nodes \
  --master-ipv4-cidr=172.16.0.0/28 \
  --shielded-secure-boot \
  --shielded-integrity-monitoring \
  --enable-dataplane-v2
```
Alternatively, if your environment operates without a default network or enforces the use of dedicated infrastructure, you must manually designate your routing targets during deployment. This requires you to already know the names of your existing custom network and the specific subnetwork located in your deployment region. You will execute the following modified command, making sure to replace the placeholder text at the very bottom with your actual network and subnet names.

```bash
gcloud beta container clusters create ${CLUSTER_NAME} \
  --project=${PROJECT_ID} \
  --location=${LOCATION} \
  --num-nodes=2 \
  --enable-ip-alias \
  --enable-private-nodes \
  --master-ipv4-cidr=172.16.0.0/28 \
  --shielded-secure-boot \
  --shielded-integrity-monitoring \
  --enable-dataplane-v2 \
  --network="YOUR_SPECIFIC_NETWORK_NAME" \
  --subnet="YOUR_SPECIFIC_SUBNET_NAME"
```

## Phase 3: Building the Isolated Node Pool and Activating Sandbox Controllers

After the primary cluster control plane finishes building, you must create a dedicated, separate node pool that is explicitly configured to isolate your untrusted agent workloads. You will execute the node pool creation command, appending the critical gVisor sandbox flag to ensure that any container scheduled here is strictly intercepted by the secure user-space kernel. To remain compliant with project settings, this secondary node pool command also incorporates the exact same suite of Shielded VM flags. Once the node pool is successfully attached, you complete the infrastructure phase by running a cluster update command to toggle the agent sandbox feature, which installs the specific custom resource definitions and orchestration controllers onto your active cluster.

```bash
gcloud container node-pools create ${NODE_POOL_NAME}   --project=${PROJECT_ID}   --cluster=${CLUSTER_NAME}   --machine-type=e2-standard-4   --location=${LOCATION}   --num-nodes=1   --image-type=cos_containerd   --sandbox=type=gvisor   --shielded-secure-boot   --shielded-integrity-monitoring

gcloud beta container clusters update ${CLUSTER_NAME}   --project=${PROJECT_ID}   --location=${LOCATION}   --enable-agent-sandbox
```

## Phase 4: Authorizing Terminal Network Access

Because the cluster is provisioned with private nodes to satisfy enterprise security constraints, the Kubernetes control plane automatically blocks all external access by default. This security measure intentionally drops traffic from your current Google Cloud Shell session. Before you can apply any manifests, you must fetch your terminal's current external IP address and explicitly whitelist it within the cluster's master authorized networks firewall.

```bash
export CLOUD_SHELL_IP=$(curl -s ifconfig.me)

gcloud container clusters update ${CLUSTER_NAME}   --project=${PROJECT_ID}   --location=${LOCATION}   --enable-master-authorized-networks   --master-authorized-networks=${CLOUD_SHELL_IP}/32
```

## Phase 5: Connecting to the Cluster and Configuring Sandbox Manifests

Now that your hardware and network authorizations are live, you must authenticate your command-line interface to interact directly with the cluster. Run the credentials command to fetch the cluster certificates and target your local tool to the new environment. Next, you need to author two local configuration files using a terminal text editor. The first file acts as your reusable blueprint for the Model Context Protocol servers, explicitly requiring the secure runtime class setting. The second file references this template and specifies how many pre-initialized, clean environments the cluster should keep running in the background to entirely eliminate cold-start latency. You will use the apply command to push both configurations live to your cluster.

```bash
gcloud container clusters get-credentials ${CLUSTER_NAME} --zone ${LOCATION}
```

```yaml
# sandbox-template.yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: mcp-server-template
  namespace: default
spec:
  podTemplate:
    metadata:
      labels:
        sandbox-type: mcp-server
    spec:
      runtimeClassName: gvisor
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector:
        sandbox.gke.io/runtime: gvisor
      tolerations:
      - key: "sandbox.gke.io/runtime"
        operator: "Equal"
        value: "gvisor"
        effect: "NoSchedule"
      securityContext:
        runAsNonRoot: true
      containers:
      - name: mcp-server
        image: python:3.11-slim
        command: ["/bin/sh", "-c"]
        args: ["echo 'Pre-warmed MCP Env Ready' && sleep 3600"]
        securityContext:
          capabilities:
            drop:
            - ALL
        resources:
          limits:
            cpu: "1"
            memory: "1Gi"
```

```yaml
# sandbox-warmpool.yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: mcp-server-warmpool
  namespace: default
spec:
  replicas: 2
  sandboxTemplateRef:
    name: mcp-server-template
```

```bash
kubectl apply -f sandbox-template.yaml
kubectl apply -f sandbox-warmpool.yaml
```

## Phase 6: Verifying the Sandbox Infrastructure State

The final phase of the setup process requires confirming that your isolated ecosystem is healthy and actively maintaining its pre-warmed pool of environments. You will use the get command to review the high-level status of your pool, ensuring that the number of available replicas perfectly matches the count you defined in your manifest. To see the actual running pods that the sandbox controller has provisioned behind the scenes, execute a targeted query filtering on the warmpool label. Seeing these pods in a running state confirms that your secure vault infrastructure is completely operational and stands fully prepared to securely accept execution claims from your primary AI agent applications.

```bash
# Check the warmpool status block for active replica counts
kubectl get sandboxwarmpool mcp-server-warmpool -o yaml

# List the active, gVisor-isolated sandbox environments
kubectl get sandbox
```

## Phase 7: Simulating Agent Requests via Sandbox Claims

When an application framework or runtime agent needs to execute code, it interacts with the control plane by submitting a SandboxClaim manifest. The orchestration controller intercepts this request, validates the schema structure against your template reference, and instantly hooks the request into one of your idling, pre-warmed sandboxes to avoid container initialization delays. You can submit this manual test configuration to verify the claim lifecycle and ensure its phase successfully transitions to bound.

```yaml
# sandbox-claim.yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxClaim
metadata:
  name: manual-agent-claim
  namespace: default
spec:
  sandboxTemplateRef:
    name: mcp-server-template
```

```bash
kubectl apply -f sandbox-claim.yaml

# Verify the orchestration controller bound the claim to an active sandbox
kubectl get sandboxclaim manual-agent-claim -o yaml
```

## Phase 8: Application-Level Health Monitoring

While the cluster infrastructure automatically provisions the core monitoring agents on each worker node, application health tracking is entirely workload-specific. The node-level kubelet service is responsible for managing and verifying pod health, but it depends on instructions embedded directly within your application manifests to know how to communicate with your code. Every workload deployed into this sandbox environment must expose a valid /healthz HTTP endpoint and define it clearly within its deployment configuration.

Engineers must include the following configuration block within the container specification of their Kubernetes deployment manifests. This explicit declaration instructs the hosting node to periodically send automated HTTP GET requests to the application, triggering an automated container restart if the app becomes unresponsive or returns an error state.

```yaml
spec:
  containers:
  - name: agent-application
    image: gcr.io/pso-ip-project-aaas/agent-image:latest
    ports:
    - containerPort: 8080
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 15
      periodSeconds: 20
    readinessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
```
