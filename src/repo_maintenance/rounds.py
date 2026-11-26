"""Go round all of bmillwood's repos, then summarise them in a table.

For each repo: run baseline, run claude-setup if the bmillwood-claude app is
installed on it, run default-branch-environment if it lists secrets for that,
and list its collaborators and Actions secrets as the surveys do. Progress and
details go to stderr, and only the table to stdout.
"""

import dataclasses
from collections.abc import Sequence


@dataclasses.dataclass(frozen=True, kw_only=True)
class Visit:
    """What to do for a repo, beyond what's done for all of them."""

    # Secrets to set on the default-branch environment, if any.
    default_branch_secrets: frozenset[str] = frozenset()


# Pushing to a cache whose signing key you hold needs both: the auth token to
# upload, and the signing key to sign. (See the descriptions of authToken and
# signingKey in https://github.com/cachix/cachix-action/blob/master/action.yml.)
CACHIX = frozenset({"CACHIX_AUTH_TOKEN", "CACHIX_SIGNING_KEY"})

HACKAGE = frozenset({"HACKAGE_AUTH_TOKEN"})

REPOS: dict[str, Visit] = {
    "bmillwood/.github": Visit(),
    "bmillwood/amber.rpm.cc": Visit(),
    "bmillwood/bluesky-tools": Visit(default_branch_secrets=HACKAGE),
    "bmillwood/delivery-status-notification": Visit(),
    "bmillwood/freecell": Visit(default_branch_secrets=CACHIX),
    "bmillwood/igzing": Visit(default_branch_secrets=CACHIX),
    "bmillwood/imitation-game": Visit(),
    "bmillwood/nur-packages": Visit(default_branch_secrets=CACHIX),
    "bmillwood/pointfree": Visit(),
    "bmillwood/renovateconfig": Visit(),
    "bmillwood/skerrible": Visit(default_branch_secrets=CACHIX),
}


def format_table(rows: Sequence[Sequence[str]]) -> str:
    """Left-aligned columns, with the first row as a header."""
    widths = [max(len(cell) for cell in column) for column in zip(*rows, strict=True)]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in rows
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(line.rstrip() for line in lines)
