"""Give the Renovate GitHub App access to a repo.

bmillwood/renovateconfig's workflow gets its tokens from octo-sts, under trust
policies in bmillwood/.github, so the only per-repo setup is being in the
app's installation, which is left to you, in the browser. (The repo also
has to be in that workflow's matrix.)
"""

import pathlib

from repo_maintenance import app_installation, plan


def _private_key(app_dir: pathlib.Path) -> pathlib.Path:
    # Fails rather than picking one, so that a rotation that leaves the
    # superseded key lying around can't quietly win.
    keys = list(app_dir.glob("*.private-key.pem"))
    if len(keys) != 1:
        raise plan.CannotPlan(
            f"want exactly one *.private-key.pem in {app_dir}, found {len(keys)}"
        )
    [key] = keys
    return key


def step(repo: plan.Repository, *, app_dir: pathlib.Path) -> list[plan.Change]:
    return app_installation.step(
        repo,
        app_name="Renovate",
        client_id=(app_dir / "client_id.txt").read_text().strip(),
        private_key=_private_key(app_dir),
    )
