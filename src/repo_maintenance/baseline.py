"""Set the repository options we want on every repo.

- No wiki or projects.
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
