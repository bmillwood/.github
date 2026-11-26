"""Go round all of bmillwood's repos, then summarise them in a table.

For each repo: run baseline, run claude-setup if the bmillwood-claude app is
installed on it, run any operations it opts into, and list its collaborators
and Actions secrets as the surveys do. Progress and details go to stderr, and only the table to stdout.
"""

from collections.abc import Sequence
from typing import Literal

type OptIn = Literal["cachix-setup"]

# Each repo, with the operations it opts into.
REPOS: dict[str, set[OptIn]] = {
    "bmillwood/.github": set(),
    "bmillwood/amber.rpm.cc": set(),
    "bmillwood/bluesky-tools": set(),
    "bmillwood/delivery-status-notification": set(),
    "bmillwood/freecell": {"cachix-setup"},
    "bmillwood/igzing": {"cachix-setup"},
    "bmillwood/imitation-game": set(),
    "bmillwood/nur-packages": {"cachix-setup"},
    "bmillwood/pointfree": set(),
    "bmillwood/renovateconfig": set(),
    "bmillwood/skerrible": {"cachix-setup"},
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
