"""Fixed dependency-free launcher transported verbatim by the release client.

Only bounded protected path/hash metadata varies per release. Verify every host
helper before loading any repository Python or Bash, then exec the fixed owner.
No supplied command, source code, environment or shell fragment is evaluated.
"""

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def launch():
    try:
        if len(sys.argv) != 2 or len(sys.argv[1]) > 32768:
            raise ValueError
        spec = json.loads(base64.b64decode(sys.argv[1], validate=True))
        if set(spec) != {
            "candidate",
            "repository",
            "python",
            "read_only",
            "pins",
            "plan_sha256",
        }:
            raise ValueError
        if type(spec["read_only"]) is not bool or not isinstance(spec["pins"], dict):
            raise ValueError
        for key in ("candidate", "repository", "python"):
            path = Path(spec[key])
            if (
                not path.is_absolute()
                or ".." in path.parts
                or (
                    key != "python"
                    and any(p.is_symlink() for p in (path, *path.parents))
                )
            ):
                raise ValueError
        if not isinstance(spec["plan_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", spec["plan_sha256"]
        ):
            raise ValueError
        os.environ["BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256"] = spec["plan_sha256"]
        candidate = Path(spec["candidate"])
        if not 12 <= len(spec["pins"]) <= 24:
            raise ValueError
        required = {
            "scripts/deploy_release_host.py",
            "scripts/lib/deployment_host.sh",
            "scripts/lib/deployment_protocol.py",
            "scripts/lib/deployment_journal.py",
        }
        if not required.issubset(spec["pins"]):
            raise ValueError
        for relative, expected in spec["pins"].items():
            if not isinstance(relative, str) or not re.fullmatch(
                r"(?:scripts|api)/[a-zA-Z0-9_./-]{1,160}", relative
            ):
                raise ValueError
            path = candidate / relative
            if ".." in Path(relative).parts or not re.fullmatch(
                r"[0-9a-f]{64}", expected
            ):
                raise ValueError
            if (
                any(p.is_symlink() for p in (path, *path.parents))
                or not path.is_file()
                or path.stat().st_size > 2 * 1024 * 1024
            ):
                raise ValueError
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError
        args = [
            "bash",
            str(candidate / "scripts/lib/deployment_host.sh"),
            "inspect" if spec["read_only"] else "lock",
            spec["repository"],
            spec["python"],
            "--repository",
            spec["repository"],
        ]
        os.execvp(args[0], args)
    except (OSError, ValueError, TypeError, KeyError):
        print('{"error":"bootstrap_refused"}', flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(launch())
