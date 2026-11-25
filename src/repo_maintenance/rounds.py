"""Go round all of bmillwood's repos, then summarise them in a table.

For each repo: run baseline, run claude-setup if the bmillwood-claude app is
installed on it, and list its collaborators and Actions secrets as the
surveys do. Progress and details go to stderr, and only the table to stdout.
"""

from collections.abc import Sequence

REPOS = [
    "bmillwood/.github",
    "bmillwood/ackermann",
    "bmillwood/amber.rpm.cc",
    "bmillwood/applicative-quoters",
    "bmillwood/backups",
    "bmillwood/backupzoah",
    "bmillwood/bluesky-tools",
    "bmillwood/bmillwood.github.io",
    "bmillwood/delivery-status-notification",
    "bmillwood/dice",
    "bmillwood/figgie",
    "bmillwood/flexiprocity",
    "bmillwood/freecell",
    "bmillwood/friendica-oauthprovider",
    "bmillwood/igzing",
    "bmillwood/imf-exchange-rates",
    "bmillwood/imitation-game",
    "bmillwood/infer",
    "bmillwood/masterword",
    "bmillwood/MaybeT-monads-tf",
    "bmillwood/misc-api",
    "bmillwood/ml-experiments",
    "bmillwood/nixos-friendica",
    "bmillwood/notcpp",
    "bmillwood/nur-packages",
    "bmillwood/packup",
    "bmillwood/pointfree",
    "bmillwood/pointfree-hse",
    "bmillwood/qc-instances",
    "bmillwood/reactions",
    "bmillwood/regex",
    "bmillwood/renovateconfig",
    "bmillwood/skerrible",
    "bmillwood/stepeval",
    "bmillwood/sunshine",
    "bmillwood/terraform-aws-ssl",
    "bmillwood/trade-game",
    "bmillwood/x2p",
]


def format_table(rows: Sequence[Sequence[str]]) -> str:
    """Left-aligned columns, with the first row as a header."""
    widths = [max(len(cell) for cell in column) for column in zip(*rows, strict=True)]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in rows
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(line.rstrip() for line in lines)
