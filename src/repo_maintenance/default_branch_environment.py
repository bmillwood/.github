"""Set secrets on an environment only the default branch can use.

Creates a "default-branch" environment whose only deployment branch is the
repo's default branch, and sets the named secrets on it. Workflow jobs that
use the secrets need `environment: default-branch`.

The environment is named for who can use it rather than what for, so that
one environment can hold all of a repo's secrets that only merged code
should see. (A job can only use one environment.)

Each secret's value is read from SECRETS_DIR/OWNER/REPO/NAME if that exists,
and otherwise from SECRETS_DIR/NAME, so secrets shared between repos only
need one file.

GitHub never reveals secret values, so an existing environment secret counts
as in sync whatever its value; delete it by hand to replace it.

The environment allows the default branch by name rather than "protected
branches only", because GitHub doesn't say whether that counts branches
protected by rulesets, and allows every branch if none count. (See
"Deployment branches and tags" in
https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments.)
"""

import pathlib
from collections.abc import Collection, Mapping
from typing import Literal

import pydantic

from repo_maintenance import github, plan

# Used in URL paths unescaped, so must be URL-safe.
ENVIRONMENT = "default-branch"


def secret_values(
    secrets_dir: pathlib.Path, *, repo_name: str, names: Collection[str]
) -> dict[str, pydantic.SecretStr]:
    """Each secret's value, from the repo's directory or else the shared one."""

    def path(name: str) -> pathlib.Path:
        repo_path = secrets_dir / repo_name / name
        return repo_path if repo_path.exists() else secrets_dir / name

    return {name: pydantic.SecretStr(path(name).read_text().strip()) for name in names}


class BranchPolicySelection(plan.WrittenWhole):
    """Which kind of deployment branch policies an environment uses.

    This is what GitHub calls an environment's deployment_branch_policy, but
    it isn't a DeploymentBranchPolicy. It says whether to allow protected
    branches, or those matching the environment's deployment branch policies.
    Exactly one of the booleans must be true -- to remove all restrictions, you
    send null instead of this object.
    https://docs.github.com/en/rest/deployments/environments
    """

    protected_branches: bool
    custom_branch_policies: bool


class Environment(pydantic.BaseModel):
    """An environment as we GET it, only the part we look at.

    Not WrittenWhole, and not what we PUT either: the PUT body has a different
    shape (e.g. wait_timer is top-level there, but under protection_rules
    here), of which we only send deployment_branch_policy.
    https://docs.github.com/en/rest/deployments/environments
    """

    deployment_branch_policy: BranchPolicySelection | None


class DeploymentBranchPolicy(plan.WrittenWhole):
    """A name pattern for branches or tags that may deploy to an environment.

    This is the shape we GET. We POST only name and type, and GitHub adds the
    IDs. We never update one in place, only DELETE and POST, so this is
    effectively WrittenWhole.
    https://docs.github.com/en/rest/deployments/branch-policies
    """

    id: int
    node_id: str
    name: str
    type: Literal["branch", "tag"]


class DeploymentBranchPolicyList(pydantic.BaseModel):
    branch_policies: list[DeploymentBranchPolicy]


def step(
    repo: plan.Repository, *, secrets: Mapping[str, pydantic.SecretStr]
) -> list[plan.Change]:
    """In order, so that the environment exists before we set its secrets."""
    environment_path = f"/repos/{repo.full_name}/environments/{ENVIRONMENT}"
    return (
        _environment(environment_path)
        + _deployment_branch_policies(environment_path, branch=repo.default_branch)
        + [
            change
            for name, value in secrets.items()
            for change in _environment_secret(environment_path, name=name, value=value)
        ]
    )


def _exists(path: str) -> bool:
    try:
        github.request("GET", path)
    except github.NotFound:
        return False
    return True


def _environment(environment_path: str) -> list[plan.Change]:
    want = BranchPolicySelection(protected_branches=False, custom_branch_policies=True)
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
                # Weirdly, this PUT seems to operate more like a PATCH,
                # updating only the fields we name rather than replacing the
                # whole object. The docs don't explicitly clarify this, it's
                # inferred from observations.
                body={"deployment_branch_policy": want.model_dump()},
            ),
        )
    ]


def _deployment_branch_policies(
    environment_path: str, *, branch: str
) -> list[plan.Change]:
    path = f"{environment_path}/deployment-branch-policies"
    try:
        have = [
            policy
            for page in github.get_pages(f"{path}?per_page=100")
            for policy in DeploymentBranchPolicyList.model_validate_json(
                page
            ).branch_policies
        ]
    except github.NotFound:
        # The environment doesn't exist yet.
        have = []
    changes = [
        plan.Change(
            description=f"remove deployment {policy.type} policy {policy.name!r}",
            action=plan.ApiCall(method="DELETE", path=f"{path}/{policy.id}"),
        )
        for policy in have
        if (policy.type, policy.name) != ("branch", branch)
    ]
    if not any((policy.type, policy.name) == ("branch", branch) for policy in have):
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
    # https://docs.github.com/en/rest/actions/secrets
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
