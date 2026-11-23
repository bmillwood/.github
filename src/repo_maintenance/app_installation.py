"""Checking that a repo is in one of our GitHub Apps' installations.

This authenticates as the app itself, since gh's token can't list an
installation's repositories. The API for adding a repo to an installation
doesn't accept gh's token either, so that part is left to you in the browser.
"""

import pathlib

import pydantic

from repo_maintenance import github, plan


class Installation(pydantic.BaseModel):
    id: int


def step(
    repo: plan.Repository,
    *,
    app_name: str,
    client_id: str,
    private_key: pathlib.Path,
) -> list[plan.Change]:
    as_app = github.app_jwt(client_id=client_id, private_key=private_key)
    try:
        # 404s if the repo isn't in the installation.
        github.request("GET", f"/repos/{repo.full_name}/installation", token=as_app)
    except github.NotFound:
        pass
    else:
        return []
    owner = repo.full_name.split("/")[0]
    installation = Installation.model_validate_json(
        github.request("GET", f"/users/{owner}/installation", token=as_app)
    )
    settings_url = f"https://github.com/settings/installations/{installation.id}"
    return [
        plan.Change(
            description=f"add to {app_name} app installation (by hand)",
            action=plan.ManualStep(
                instruction=f"Add {repo.full_name} at {settings_url}"
            ),
        )
    ]
