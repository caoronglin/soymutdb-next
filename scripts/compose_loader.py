"""Load a Compose file with the platform's own tags understood.

Compose files use the Compose-specific `!reset` tag to discard a value
(`build: !reset null`) when applying an explicit local override. The production
topology no longer needs it (release services carry no `build:` and the local
override only rewrites `image:` scalars), but the tag stays supported so the
development/local overlays can keep using it. Plain `yaml.safe_load` refuses it:

    could not determine a constructor for the tag '!reset'

Every test that parses the production topology therefore shares this loader
instead of each one growing its own copy of the same three lines — the copies
are how the development overlay's loader and the production contract's loader
already disagreed once (the dev one knew `!reset`, the production one did not,
and adding a single `!reset` to the base file broke sixteen tests at once).

The tag is NOT resolved away: it stays visible to callers as the literal
`"!reset"`, because a test asserting "this key is discarded" must be able to see
that it is, rather than seeing `None` from either a real null or a discarded
value.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RESET = "!reset"
OVERRIDE = "!override"


class ComposeLoader(yaml.SafeLoader):
    """SafeLoader that understands the Compose `!reset` / `!override` tags."""

    def _tag(self, node: yaml.Node) -> object:
        if isinstance(node, yaml.ScalarNode):
            return self.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return self.construct_sequence(node)
        return self.construct_mapping(node)


ComposeLoader.add_constructor(RESET, ComposeLoader._tag)
ComposeLoader.add_constructor(OVERRIDE, ComposeLoader._tag)


def load_compose(path: Path | str) -> dict:
    """Parse a Compose document from a path."""
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=ComposeLoader)
