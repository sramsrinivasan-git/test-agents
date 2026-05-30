"""Tool: analyze who has what IAM access to a resource."""

from __future__ import annotations

from typing import Any

from google.cloud import asset_v1

from gcp_cloud_asset.common import get_client, resolve_scope


def analyze_iam_policy(
    resource: str | None = None,
    identity: str | None = None,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    expand_groups: bool = False,
    expand_roles: bool = False,
    output_resource_edges: bool = True,
) -> dict[str, Any]:
    """Analyze who has what IAM access to a specific resource (or within a scope).

    Uses the Cloud Asset Policy Analyzer to perform a structured access
    analysis — much faster and more precise than manually parsing IAM policies.
    At least one of `resource`, `identity`, `roles`, or `permissions` must
    be provided to narrow the analysis.

    When to use:
      - "Who has storage.objects.delete permission on bucket my-bucket?"
      - "What can serviceAccount:sa@p.iam.gserviceaccount.com do in this project?"
      - "Does user:alice@example.com have roles/bigquery.admin anywhere?"
      - Security audits: enumerate all identities with owner/editor access.

    Args:
        resource: Full resource name to analyze access on, e.g.
            '//storage.googleapis.com/projects/_/buckets/my-bucket'
            '//cloudresourcemanager.googleapis.com/projects/my-proj'
            '//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1'
            Omit to analyze across all resources in the scope.
        identity: Identity to check access for. One of:
            - 'user:alice@example.com'
            - 'serviceAccount:sa@project.iam.gserviceaccount.com'
            - 'group:eng@example.com'
        roles: List of roles to restrict analysis to, e.g.
            ['roles/storage.admin', 'roles/editor'].
        permissions: List of permissions to check, e.g.
            ['storage.buckets.delete', 'compute.instances.start'].
        scope: Analysis scope resource name. One of:
            - 'projects/<id-or-number>'
            - 'folders/<folder-number>'
            - 'organizations/<org-number>'
            Falls back to project_id / GOOGLE_CLOUD_PROJECT.
        project_id: GCP project ID. Used when scope is not given.
            Falls back to GOOGLE_CLOUD_PROJECT env var.
        expand_groups: If True, expand group memberships so individual
            user members are shown. Default False.
        expand_roles: If True, expand role definitions to show constituent
            permissions. Default False.
        output_resource_edges: If True, include resource ancestry edges in
            the result to show where each binding is inherited from.
            Default True.

    Returns:
        dict with keys:
            - scope (str): the scope analyzed.
            - main_analysis (list[dict]): each entry is an access tuple
              {identity_selector, access_selector, resource_selector,
               condition, fully_explored} showing who can do what.
            - service_account_impersonation (list[dict]): any impersonation
              paths found.
            - fully_explored (bool): whether the analysis was exhaustive
              (may be False if the policy set is very large).
    """
    resolved_scope = resolve_scope(scope, project_id)
    client = get_client()

    selector_args: dict[str, Any] = {}
    if identity:
        selector_args["identity"] = asset_v1.IamPolicyAnalysisQuery.IdentitySelector(
            identity=identity
        )
    if resource:
        selector_args["resource_selector"] = asset_v1.IamPolicyAnalysisQuery.ResourceSelector(
            full_resource_name=resource
        )
    if roles or permissions:
        selector_args["access_selector"] = asset_v1.IamPolicyAnalysisQuery.AccessSelector(
            roles=roles or [],
            permissions=permissions or [],
        )

    query = asset_v1.IamPolicyAnalysisQuery(
        scope=resolved_scope,
        **selector_args,
    )

    options = asset_v1.IamPolicyAnalysisQuery.Options(
        expand_groups=expand_groups,
        expand_roles=expand_roles,
        output_resource_edges=output_resource_edges,
    )
    query.options = options

    request = asset_v1.AnalyzeIamPolicyRequest(analysis_query=query)
    response = client.analyze_iam_policy(request=request)

    main_analysis = []
    for result in response.main_analysis.analysis_results:
        access_tuples = []
        for acl in result.access_control_lists:
            accesses = [{"role": a.role, "permission": a.permission} for a in acl.accesses]
            resources = [{"resource": r.full_resource_name, "analysis_state": r.analysis_state.code if r.analysis_state else None} for r in acl.resources]
            access_tuples.append({"accesses": accesses, "resources": resources})
        identities = []
        if result.identity_list:
            for ident in result.identity_list.identities:
                identities.append({
                    "name": ident.name,
                    "analysis_state": ident.analysis_state.code if ident.analysis_state else None,
                })
        main_analysis.append({
            "attached_resource_full_name": result.attached_resource_full_name,
            "access_control_lists": access_tuples,
            "identities": identities,
            "fully_explored": result.fully_explored,
        })

    return {
        "scope": resolved_scope,
        "main_analysis": main_analysis,
        "fully_explored": response.main_analysis.fully_explored,
    }
