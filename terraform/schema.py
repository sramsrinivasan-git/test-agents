"""Declarative schema of the GCP resources required to run the
gcp-log-analyzer MCP server on Cloud Run.

This file is intentionally framework-free: it uses plain dataclasses so it
can be consumed by Terraform-generators, Pulumi, gcloud-script renderers,
or read by a human as the source of truth for what needs to exist in GCP.

The bottom of the file (`DEPLOYMENT`) wires the individual resource
schemas together into the concrete desired state for this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectConfig:
    """The two GCP projects involved in a deployment.

    `host_project` runs the Cloud Run service (compute + Artifact Registry).
    `logs_project` is the project whose Cloud Logging data the server reads.
    They are commonly the same project but can differ for cross-project
    log analysis.
    """

    host_project: str
    logs_project: str
    region: str = "us-central1"


@dataclass(frozen=True)
class EnabledApi:
    """A GCP service / API that must be enabled on `project`."""

    service: str
    project_attr: str = "host_project"


@dataclass(frozen=True)
class ServiceAccount:
    """A user-managed service account."""

    account_id: str
    display_name: str
    project_attr: str = "host_project"

    def email(self, project: str) -> str:
        return f"{self.account_id}@{project}.iam.gserviceaccount.com"


@dataclass(frozen=True)
class IamBinding:
    """A project-level IAM role binding for a single member."""

    project_attr: str
    member: str
    role: str


@dataclass(frozen=True)
class CloudRunService:
    """A Cloud Run (fully managed) service definition."""

    name: str
    source_path: str
    service_account_id: str
    env_vars: dict[str, str] = field(default_factory=dict)
    cpu: str = "1"
    memory: str = "512Mi"
    min_instances: int = 0
    max_instances: int = 3
    allow_unauthenticated: bool = False
    project_attr: str = "host_project"


@dataclass(frozen=True)
class CloudRunInvoker:
    """A run.invoker binding granting one principal access to call a service."""

    service_name: str
    member: str
    role: str = "roles/run.invoker"
    project_attr: str = "host_project"


@dataclass(frozen=True)
class Deployment:
    """The full desired state of GCP for this MCP server."""

    project: ProjectConfig
    apis: list[EnabledApi]
    service_accounts: list[ServiceAccount]
    iam_bindings: list[IamBinding]
    cloud_run_services: list[CloudRunService]
    invokers: list[CloudRunInvoker]


SERVICE_ACCOUNT_ID = "gcp-log-analyzer-mcp"
SERVICE_NAME = "gcp-log-analyzer-mcp"

SA_EMAIL_TEMPLATE = f"serviceAccount:{SERVICE_ACCOUNT_ID}@{{host_project}}.iam.gserviceaccount.com"
COMPUTE_SA_TEMPLATE = "serviceAccount:{project_number}-compute@developer.gserviceaccount.com"


DEPLOYMENT = Deployment(
    project=ProjectConfig(
        host_project="REPLACE_WITH_HOST_PROJECT",
        logs_project="REPLACE_WITH_LOGS_PROJECT",
        region="us-central1",
    ),
    apis=[
        EnabledApi("run.googleapis.com"),
        EnabledApi("cloudbuild.googleapis.com"),
        EnabledApi("artifactregistry.googleapis.com"),
        EnabledApi("logging.googleapis.com"),
        EnabledApi("logging.googleapis.com", project_attr="logs_project"),
    ],
    service_accounts=[
        ServiceAccount(
            account_id=SERVICE_ACCOUNT_ID,
            display_name="GCP Log Analyzer MCP Server",
        ),
    ],
    iam_bindings=[
        IamBinding(
            project_attr="logs_project",
            member=SA_EMAIL_TEMPLATE,
            role="roles/logging.viewer",
        ),
        IamBinding(
            project_attr="host_project",
            member=COMPUTE_SA_TEMPLATE,
            role="roles/cloudbuild.builds.builder",
        ),
    ],
    cloud_run_services=[
        CloudRunService(
            name=SERVICE_NAME,
            source_path="mcp_servers/gcp_log_analyzer",
            service_account_id=SERVICE_ACCOUNT_ID,
            env_vars={
                "GOOGLE_CLOUD_PROJECT": "{logs_project}",
                "MCP_TRANSPORT": "streamable-http",
            },
            cpu="1",
            memory="512Mi",
            min_instances=0,
            max_instances=3,
            allow_unauthenticated=False,
        ),
    ],
    invokers=[
        CloudRunInvoker(
            service_name=SERVICE_NAME,
            member="user:REPLACE_WITH_INVOKER_EMAIL",
        ),
    ],
)
