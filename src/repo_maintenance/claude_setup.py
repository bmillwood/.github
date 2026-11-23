"""Run branch-protection, and give the bmillwood-claude GitHub App access.

Adding a repo to the app's installation is left to you, in the browser.
"""

import pathlib

from repo_maintenance import app_installation, plan

APP_SLUG = "bmillwood-claude"
# Not looked up from the slug: the app is private, and GET /apps/{slug} 404s
# for gh's token. (The JWT needs this to be known first, so asking as the app
# isn't an option either.)
APP_CLIENT_ID = "Iv23liT64156LSTP1TAa"


def step(repo: plan.Repository, *, app_private_key: pathlib.Path) -> list[plan.Change]:
    return app_installation.step(
        repo,
        app_name=APP_SLUG,
        client_id=APP_CLIENT_ID,
        private_key=app_private_key,
    )
