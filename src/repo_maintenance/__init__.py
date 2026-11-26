"""Idempotently apply packages of GitHub configuration, or survey it.

Operates on the named repos and all those of --all-owned-by, or the current
repo if there are neither.
Authenticates with gh's token (via `gh auth token`), which needs to belong to
a repo admin.

By default, operations only report what would change, exiting 1 if anything
would. With --apply, they make the changes, then check again that nothing is
left.
"""

import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Annotated

import cyclopts
import pydantic

from repo_maintenance import (
    app_installation,
    baseline,
    branch_protection,
    claude_setup,
    default_branch_environment,
    github,
    plan,
    rounds,
    survey,
)

app = cyclopts.App(help=__doc__)

Repo = Annotated[str, cyclopts.Parameter(name="OWNER/REPO")]
AllOwnedBy = Annotated[
    tuple[str, ...],
    cyclopts.Parameter(
        negative=(),
        metavar="OWNER",
        show_default=False,
        help="Also operate on all of this user or organisation's repos that you"
        " administer, except forks and archived ones. Can be repeated.",
    ),
]
Apply = Annotated[
    bool,
    cyclopts.Parameter(
        negative=(), help="Make the changes, then check again that nothing is left."
    ),
]


def _print_changes(*, repo_name: str, changes: list[plan.Change]) -> None:
    if not changes:
        print(f"{repo_name}: in sync")
    for change in changes:
        print(f"{repo_name}: {change.description}")
        for line in change.detail.splitlines():
            print(f"    {line}")


def _plan(*, repo_name: str, steps: Sequence[plan.Step]) -> list[plan.Change] | None:
    """The changes needed, or None (having said why) if we couldn't tell."""
    try:
        repo = plan.Repository.model_validate_json(
            github.request("GET", f"/repos/{repo_name}")
        )
        changes = [change for step in steps for change in step(repo)]
    except (github.RequestFailed, plan.CannotPlan) as error:
        print(f"{repo_name}: {error}", file=sys.stderr)
        return None
    _print_changes(repo_name=repo_name, changes=changes)
    return changes


def _do(action: plan.ApiCall | plan.SetSecret | plan.ManualStep) -> None:
    match action:
        case plan.ApiCall(method=method, path=path, body=body):
            github.request(
                method, path, body=None if body is None else json.dumps(body)
            )
        case plan.SetSecret(path=path, public_key_path=public_key_path, value=value):
            github.put_secret(path, public_key_path=public_key_path, value=value)
        case plan.ManualStep(instruction=instruction):
            input(f"{instruction}, then press Enter: ")


def _sync(
    *, repo_name: str, steps: Sequence[plan.Step], apply: bool
) -> list[plan.Change] | None:
    """The changes (still) needed, or None if we couldn't tell."""
    changes = _plan(repo_name=repo_name, steps=steps)
    if not changes or not apply:
        return changes
    for change in changes:
        print(f"{repo_name}: {change.action}")
        try:
            _do(change.action)
        except github.RequestFailed as error:
            print(f"{repo_name}: {error}", file=sys.stderr)
            print(f"{repo_name}: not attempting any further changes", file=sys.stderr)
            break
    print(f"{repo_name}: re-checking")
    return _plan(repo_name=repo_name, steps=steps)


class _Owner(pydantic.BaseModel):
    login: str


class _Permissions(pydantic.BaseModel):
    admin: bool


class _ListedRepo(pydantic.BaseModel):
    full_name: str
    owner: _Owner
    fork: bool
    archived: bool
    permissions: _Permissions


def _owner_repos(owner: str) -> list[str]:
    # Unlike /users/{owner}/repos, this includes private repos, and covers
    # organisations as well as users.
    listed = [
        repo
        for page in github.get_pages(
            "/user/repos?affiliation=owner,organization_member&per_page=100"
        )
        for repo in pydantic.TypeAdapter(list[_ListedRepo]).validate_json(page)
    ]
    return [
        repo.full_name
        for repo in listed
        if repo.owner.login.lower() == owner.lower()
        and repo.permissions.admin
        and not repo.fork
        and not repo.archived
    ]


def _repo_names(*, repos: Sequence[str], owners: Sequence[str]) -> list[str]:
    repos = list(repos)
    for owner in owners:
        try:
            repos += _owner_repos(owner)
        except github.RequestFailed as error:
            print(f"listing repos: {error}", file=sys.stderr)
            sys.exit(1)
    if not repos and not owners:
        try:
            repos = [github.current_repo()]
        except subprocess.CalledProcessError as error:
            print("No OWNER/REPO given, and no current repo.", file=sys.stderr)
            sys.exit(error.returncode)
    return repos


def _run(
    *,
    repos: Sequence[str],
    owners: Sequence[str],
    steps: Sequence[plan.Step],
    apply: bool,
) -> None:
    repos = _repo_names(repos=repos, owners=owners)
    results = [
        _sync(repo_name=repo_name, steps=steps, apply=apply) == []
        for repo_name in repos
    ]
    sys.exit(0 if all(results) else 1)


@app.command(help=baseline.__doc__)
def _baseline(
    *repos: Repo, all_owned_by: AllOwnedBy = (), apply: Apply = False
) -> None:
    _run(repos=repos, owners=all_owned_by, steps=[baseline.step], apply=apply)


@app.command(help=branch_protection.__doc__)
def _branch_protection(
    *repos: Repo, all_owned_by: AllOwnedBy = (), apply: Apply = False
) -> None:
    _run(repos=repos, owners=all_owned_by, steps=[branch_protection.step], apply=apply)


ClaudeAppPrivateKey = Annotated[
    cyclopts.types.ExistingFile,
    cyclopts.Parameter(help=f"Private key of the {claude_setup.APP_SLUG} app."),
]


def _claude_setup_steps(app_private_key: pathlib.Path) -> list[plan.Step]:
    return [
        branch_protection.step,
        lambda repo: claude_setup.step(repo, app_private_key=app_private_key),
    ]


@app.command(help=claude_setup.__doc__)
def _claude_setup(
    *repos: Repo,
    app_private_key: ClaudeAppPrivateKey,
    all_owned_by: AllOwnedBy = (),
    apply: Apply = False,
) -> None:
    _run(
        repos=repos,
        owners=all_owned_by,
        steps=_claude_setup_steps(app_private_key),
        apply=apply,
    )


SecretsDir = Annotated[
    cyclopts.types.ExistingDirectory,
    cyclopts.Parameter(
        help="Directory of secret values, as OWNER/REPO/NAME or (shared) NAME."
    ),
]


@app.command(help=default_branch_environment.__doc__)
def _default_branch_environment(
    *repos: Repo,
    secrets_dir: SecretsDir,
    secret: Annotated[
        tuple[str, ...],
        cyclopts.Parameter(
            negative=(),
            help="Name of a secret to set on the environment. Can be repeated.",
        ),
    ],
    all_owned_by: AllOwnedBy = (),
    apply: Apply = False,
) -> None:
    _run(
        repos=repos,
        owners=all_owned_by,
        steps=[
            lambda repo: default_branch_environment.step(
                repo,
                secrets=default_branch_environment.secret_values(
                    secrets_dir, repo_name=repo.full_name, names=secret
                ),
            )
        ],
        apply=apply,
    )


def _survey(
    *,
    repos: Sequence[str],
    owners: Sequence[str],
    describe: Callable[[str], frozenset[str]],
) -> None:
    repo_names = _repo_names(repos=repos, owners=owners)
    sys.exit(0 if survey.survey(repo_names, describe=describe) else 1)


@app.command(help=survey.secret_names.__doc__)
def _secrets_survey(*repos: Repo, all_owned_by: AllOwnedBy = ()) -> None:
    _survey(repos=repos, owners=all_owned_by, describe=survey.secret_names)


@app.command(help=survey.collaborators.__doc__)
def _collaborators_survey(*repos: Repo, all_owned_by: AllOwnedBy = ()) -> None:
    _survey(repos=repos, owners=all_owned_by, describe=survey.collaborators)


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Cell:
    text: str
    # Whether this is fine as it is, for the exit status.
    ok: bool


def _changes_cell(changes: list[plan.Change] | None) -> _Cell:
    match changes:
        case None:
            return _Cell(text="error", ok=False)
        case []:
            return _Cell(text="in sync", ok=True)
        case _:
            return _Cell(text=f"{len(changes)} change(s) needed", ok=False)


def _claude_setup_cell(
    repo_name: str, *, claude_private_key: pathlib.Path, apply: bool
) -> _Cell:
    try:
        claude_app_installed = app_installation.installed(
            repo_name,
            client_id=claude_setup.APP_CLIENT_ID,
            private_key=claude_private_key,
        )
    except github.RequestFailed as error:
        print(f"{repo_name}: {error}", file=sys.stderr)
        return _Cell(text="error", ok=False)
    if not claude_app_installed:
        return _Cell(text="app not installed", ok=True)
    return _changes_cell(
        _sync(
            repo_name=repo_name,
            steps=_claude_setup_steps(claude_private_key),
            apply=apply,
        )
    )


def _survey_cell(repo_name: str, *, describe: Callable[[str], frozenset[str]]) -> _Cell:
    try:
        return _Cell(text=", ".join(sorted(describe(repo_name))) or "(none)", ok=True)
    except github.RequestFailed as error:
        print(f"{repo_name}: {error}", file=sys.stderr)
        return _Cell(text="error", ok=False)


@app.command(help=rounds.__doc__)
def _rounds(
    *,
    claude_private_key: ClaudeAppPrivateKey,
    secrets_dir: SecretsDir,
    apply: Apply = False,
) -> None:
    # All read up front, so that a missing file stops us before we start.
    default_branch_secrets = {
        repo_name: default_branch_environment.secret_values(
            secrets_dir, repo_name=repo_name, names=visit.default_branch_secrets
        )
        for repo_name, visit in rounds.REPOS.items()
    }
    with contextlib.redirect_stdout(sys.stderr):
        rows = {
            repo_name: [
                _changes_cell(
                    _sync(repo_name=repo_name, steps=[baseline.step], apply=apply)
                ),
                _claude_setup_cell(
                    repo_name, claude_private_key=claude_private_key, apply=apply
                ),
                _changes_cell(
                    _sync(
                        repo_name=repo_name,
                        steps=[
                            lambda repo: default_branch_environment.step(
                                repo, secrets=default_branch_secrets[repo.full_name]
                            )
                        ],
                        apply=apply,
                    )
                )
                if visit.default_branch_secrets
                else _Cell(text="-", ok=True),
                # After the operations, so as to show their results.
                _survey_cell(repo_name, describe=survey.collaborators),
                _survey_cell(repo_name, describe=survey.secret_names),
            ]
            for repo_name, visit in rounds.REPOS.items()
        }
    print(
        rounds.format_table(
            [
                [
                    "repo",
                    "baseline",
                    "claude-setup",
                    "default-branch env",
                    "collaborators",
                    "secrets",
                ],
                *(
                    [repo_name] + [cell.text for cell in cells]
                    for repo_name, cells in rows.items()
                ),
            ]
        )
    )
    sys.exit(0 if all(cell.ok for cells in rows.values() for cell in cells) else 1)


def main() -> None:
    # So that stdout and stderr interleave sensibly even when piped.
    assert isinstance(sys.stdout, io.TextIOWrapper)
    sys.stdout.reconfigure(line_buffering=True)
    app()
