"""Set the repository options we want on every repo.

- No wiki or projects, unless there's a wiki page or a project linked to the
  repo, since disabling them would hide those.
- Merge commits only, no squash or rebase merges.
- Delete head branches once their PRs are merged.
- Always suggest updating PR branches, and allow auto-merge (so the repo must
  be public, since we assume private repos are on a free plan).
- Require approval to run Actions workflows on fork PRs from all external
  contributors.
"""

import pydantic

from repo_maintenance import github, plan


class Settings(pydantic.BaseModel):
    """The repository settings we manage, as in GET/PATCH /repos/{repo}."""

    has_wiki: bool
    has_projects: bool
    allow_merge_commit: bool
    allow_squash_merge: bool
    allow_rebase_merge: bool
    delete_branch_on_merge: bool
    allow_update_branch: bool
    allow_auto_merge: bool


DESIRED = Settings(
    has_wiki=False,
    has_projects=False,
    # Explicitly, since disabling the other two is refused if it would leave
    # no merge method at all.
    allow_merge_commit=True,
    allow_squash_merge=False,
    allow_rebase_merge=False,
    delete_branch_on_merge=True,
    allow_update_branch=True,
    allow_auto_merge=True,
)


def step(repo: plan.Repository) -> list[plan.Change]:
    return _repository_settings(repo) + _fork_pr_approval(repo)


def _repository_settings(repo: plan.Repository) -> list[plan.Change]:
    have = Settings.model_validate_json(
        github.request("GET", f"/repos/{repo.full_name}")
    )
    have_fields = have.model_dump()
    patch = {k: v for k, v in DESIRED.model_dump().items() if have_fields[k] != v}
    if patch.get("has_wiki") is False and github.wiki_has_pages(repo.full_name):
        raise plan.CannotPlan("the wiki has pages, which disabling it would hide")
    if patch.get("has_projects") is False and _linked_project_count(repo) > 0:
        raise plan.CannotPlan(
            "projects are linked to the repo, which disabling projects would hide"
        )
    if repo.private and "allow_auto_merge" in patch:
        # On a free plan, GitHub accepts the PATCH but ignores it.
        raise plan.CannotPlan("auto-merge isn't available for private repos")
    if not patch:
        return []
    return [
        plan.Change(
            description="update repository settings",
            detail="\n".join(
                f"{k}: {have_fields[k]!r} -> {v!r}" for k, v in patch.items()
            ),
            action=plan.ApiCall(
                method="PATCH", path=f"/repos/{repo.full_name}", body=patch
            ),
        )
    ]


class _ProjectsV2(pydantic.BaseModel):
    totalCount: int


class _Repository(pydantic.BaseModel):
    projectsV2: _ProjectsV2


class _ProjectsQuery(pydantic.BaseModel):
    repository: _Repository


def _linked_project_count(repo: plan.Repository) -> int:
    # Only Projects (v2): classic projects are gone, even from the API.
    owner, name = repo.full_name.split("/")
    data = github.graphql(
        """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            projectsV2 { totalCount }
          }
        }
        """,
        owner=owner,
        name=name,
    )
    return _ProjectsQuery.model_validate(data).repository.projectsV2.totalCount


class ForkPrApproval(pydantic.BaseModel):
    """As in GET/PUT /repos/{repo}/actions/permissions/fork-pr-contributor-approval."""

    approval_policy: str


def _fork_pr_approval(repo: plan.Repository) -> list[plan.Change]:
    path = f"/repos/{repo.full_name}/actions/permissions/fork-pr-contributor-approval"
    have = ForkPrApproval.model_validate_json(github.request("GET", path))
    want = ForkPrApproval(approval_policy="all_external_contributors")
    if have == want:
        return []
    return [
        plan.Change(
            description="require approval for fork PR workflows",
            detail=f"approval_policy: {have.approval_policy!r} -> "
            f"{want.approval_policy!r}",
            action=plan.ApiCall(method="PUT", path=path, body=want.model_dump()),
        )
    ]
