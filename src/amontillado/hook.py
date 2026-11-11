"""Running the `on_change` hook after a command wrote under the library roots.

docs/design.md, "git-annex libraries: decisions" 5. The CLI records a writing command's
changes (`amontillado.changes`) and, when `on_change` is set, runs it under `sh -c` once per
root written to, the root's payload as JSON on stdin and AMO_ROOT and AMO_COMMAND in its
environment. amo's writes stand whatever the hook does: a hook that fails is a warning.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from logging import getLogger

from amontillado.changes import Recorder
from amontillado.config import Config, shell_status

logger = getLogger(__name__)


def run_on_change(config: Config, recorder: Recorder, command: str) -> None:
    """Run `config.on_change` for each root `recorder` saw a change under (none if unset)."""
    if config.on_change is None:
        return
    roots = (*config.library_roots, config.nsfw_root)
    for root, payload in recorder.payloads(command, roots):
        # AMO_* from amo's own environment would be stale: only this run's are set.
        env = {k: v for k, v in os.environ.items() if not k.startswith("AMO_")}
        env |= {"AMO_ROOT": str(root), "AMO_COMMAND": command}
        logger.debug("%s: on_change: %d changes", root, len(payload["changes"]))
        try:
            result = subprocess.run(
                ["sh", "-c", config.on_change],
                input=json.dumps(payload, default=str),
                text=True,
                env=env,
                stdout=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            logger.warning("%s: on_change could not run: %s", root, exc)
            continue
        # Its output to stderr: amo's own stdout is data (`amo crop` prints the new file).
        sys.stderr.write(result.stdout)
        if result.returncode != 0:
            logger.warning(
                "%s: on_change failed (%s); amo's changes stand",
                root,
                shell_status(result.returncode),
            )
