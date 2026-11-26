"""Move Cachix credentials into an environment only the default branch can use.

Creates a "cachix" environment whose only deployment branch is the default
branch, gives it the CACHIX_SIGNING_KEY and CACHIX_AUTH_TOKEN secrets, and
then deletes any repository secrets of those names. Workflow jobs that use the
secrets need `environment: cachix`.

Both secrets are needed to push to a cache whose signing key you hold: the
auth token to upload, and the signing key to sign.

GitHub never reveals secret values, so an existing environment secret counts
as in sync whatever its value; delete it by hand to replace it.

The environment allows the default branch by name rather than "protected
branches only", because GitHub doesn't say whether that counts branches
protected by rulesets, and allows every branch if none count.

The environment is assumed to be ours alone: updating its branch policy
may reset settings that we don't manage, such as required reviewers.
"""

import pydantic

from repo_maintenance import github, plan

ENVIRONMENT = "cachix"


class BranchPolicy(plan.WrittenWhole):
    """As in an environment's deployment_branch_policy."""

    protected_branches: bool
    custom_branch_policies: bool


class Environment(pydantic.BaseModel):
    deployment_branch_policy: BranchPolicy | None


class NamePattern(pydantic.BaseModel):
    """A deployment branch (or tag) policy, as in .../deployment-branch-policies."""

    id: int
    name: str
    type: str


class NamePatternList(pydantic.BaseModel):
    branch_policies: list[NamePattern]


def step(
    repo: plan.Repository,
    *,
    signing_key: pydantic.SecretStr,
    auth_token: pydantic.SecretStr,
) -> list[plan.Change]:
    """In order, so that repository secrets only go once all the others are set."""
    secrets = {"CACHIX_SIGNING_KEY": signing_key, "CACHIX_AUTH_TOKEN": auth_token}
    environment_path = f"/repos/{repo.full_name}/environments/{ENVIRONMENT}"
    return (
        _environment(environment_path)
        + _name_patterns(environment_path, branch=repo.default_branch)
        + [
            change
            for name, value in secrets.items()
            for change in _environment_secret(environment_path, name=name, value=value)
        ]
        + [change for name in secrets for change in _repository_secret(repo, name=name)]
    )


def _exists(path: str) -> bool:
    try:
        github.request("GET", path)
    except github.NotFound:
        return False
    return True


def _environment(environment_path: str) -> list[plan.Change]:
    want = BranchPolicy(protected_branches=False, custom_branch_policies=True)
    try:
        have = Environment.model_validate_json(
            github.request("GET", environment_path)
        ).deployment_branch_policy
    except github.NotFound:
        description = f"create environment {ENVIRONMENT!r}"
        detail = ""
    else:
        if have == want:
            return []
        description = f"update environment {ENVIRONMENT!r}"
        detail = (
            "deployment_branch_policy: "
            f"{have and have.model_dump()!r} -> {want.model_dump()!r}"
        )
    return [
        plan.Change(
            description=description,
            detail=detail,
            action=plan.ApiCall(
                method="PUT",
                path=environment_path,
                body={"deployment_branch_policy": want.model_dump()},
            ),
        )
    ]


def _name_patterns(environment_path: str, *, branch: str) -> list[plan.Change]:
    path = f"{environment_path}/deployment-branch-policies"
    try:
        have = [
            pattern
            for page in github.get_pages(f"{path}?per_page=100")
            for pattern in NamePatternList.model_validate_json(page).branch_policies
        ]
    except github.NotFound:
        # The environment doesn't exist yet.
        have = []
    changes = [
        plan.Change(
            description=f"remove deployment {pattern.type} pattern {pattern.name!r}",
            action=plan.ApiCall(method="DELETE", path=f"{path}/{pattern.id}"),
        )
        for pattern in have
        if (pattern.type, pattern.name) != ("branch", branch)
    ]
    if not any((pattern.type, pattern.name) == ("branch", branch) for pattern in have):
        changes.append(
            plan.Change(
                description=f"allow deployments from {branch}",
                action=plan.ApiCall(
                    method="POST", path=path, body={"name": branch, "type": "branch"}
                ),
            )
        )
    return changes


def _environment_secret(
    environment_path: str, *, name: str, value: pydantic.SecretStr
) -> list[plan.Change]:
    path = f"{environment_path}/secrets/{name}"
    # Also 404s if the environment doesn't exist yet.
    if _exists(path):
        return []
    return [
        plan.Change(
            description=f"set environment secret {name}",
            action=plan.SetSecret(
                path=path,
                public_key_path=f"{environment_path}/secrets/public-key",
                value=value,
            ),
        )
    ]


def _repository_secret(repo: plan.Repository, *, name: str) -> list[plan.Change]:
    path = f"/repos/{repo.full_name}/actions/secrets/{name}"
    if not _exists(path):
        return []
    return [
        plan.Change(
            description=f"delete repository secret {name}",
            action=plan.ApiCall(method="DELETE", path=path),
        )
    ]
