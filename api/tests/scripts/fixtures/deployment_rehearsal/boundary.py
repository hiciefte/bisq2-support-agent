#!/usr/bin/env python3
"""Networkless external-command model. Never usable against a real Docker daemon."""

import hashlib
import io
import json
import os
import signal
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "boundary-state.json"
state = json.loads(STATE.read_text())
args = sys.argv[1:]
command = Path(sys.argv[0]).name
state["calls"].append({"boundary": command, "argv": args})


def save():
    STATE.write_text(json.dumps(state, sort_keys=True))


def emit(value):
    print(json.dumps(value) if not isinstance(value, str) else value)


def select_containers(tokens):
    values = list(state["containers"].values())
    for token in tokens:
        if token.startswith("label=com.docker.compose.service="):
            service = token.split("=", 2)[-1]
            values = [
                value
                for value in values
                if value["Config"]["Labels"]["com.docker.compose.service"] == service
            ]
    return values


def inspected(tokens):
    ids = [token for token in tokens if len(token) == 64]
    values = [value for value in state["containers"].values() if value["Id"] in ids]
    assert len(values) == len(ids), ("unknown inspect", tokens)
    return values


def docker():
    if args[0] == "ps":
        emit("\n".join(value["Id"] for value in select_containers(args)))
    elif args[0] == "inspect":
        values = inspected(args)
        template = None
        for index, token in enumerate(args):
            if token == "--format":
                template = args[index + 1]
            elif token.startswith("--format="):
                template = token.split("=", 1)[1]
        if template:
            value = values[0]
            labels = value["Config"]["Labels"]
            if "|" in template:
                fields = {
                    '{{index .Config.Labels "' + key + '"}}': content
                    for key, content in labels.items()
                }
                fields["{{.State.Status}}"] = value["State"]["Status"]
                fields["{{.State.Paused}}"] = str(value["State"]["Paused"]).lower()
                fields["{{.State.Running}}"] = str(value["State"]["Running"]).lower()
                emit("|".join(fields[field] for field in template.split("|")))
            elif '"com.docker.compose.project"' in template:
                emit("fixture")
            elif '"com.docker.compose.service"' in template:
                emit(labels["com.docker.compose.service"])
            elif ".State.Health" in template:
                emit("healthy")
            elif ".State.Status" in template:
                emit("running")
            else:
                raise AssertionError(("unknown template", template))
        else:
            emit(values)
    elif args[:2] == ["image", "inspect"]:
        emit([state["images"][args[-1]]])
    elif args[0] in ("pause", "unpause"):
        values = inspected(args)
        assert len(values) == 1
        values[0]["State"]["Paused"] = args[0] == "pause"
        values[0]["State"]["Status"] = "paused" if args[0] == "pause" else "running"
        emit(values[0]["Id"])
    elif args[0] == "cp":
        assert args[-1] == "-" and args[-2].endswith(":/etc/crontabs/root")
        raw = state["cron"].encode()
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            info = tarfile.TarInfo("root")
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
        sys.stdout.buffer.write(output.getvalue())
    elif args[0] == "exec":
        value = inspected(args)[0]
        if args[2:] == ["nginx", "-s", "reload"]:
            state["nginx_reloads"] += 1
        elif args[-1] == "/app/.next/BUILD_ID":
            emit(state["build_ids"][value["Image"]])
        elif args[-1].endswith("/health/ready"):
            emit({"status": "ready"})
        elif args[-1].endswith("/health"):
            emit({"build_id": state["build_ids"][value["Image"]]})
        else:
            raise AssertionError(("unknown exec", args))
    elif args[0] == "run":
        assert "--network" in args and args[args.index("--network") + 1] == "none"
        assert args[-1] == "/app/.next/BUILD_ID"
        emit(state["build_ids"][args[-2]])
    elif args[0] == "compose":
        options = args[1:]
        overlays = []
        while options and options[0] in ("--project-name", "-f"):
            key, value, *options = options
            if key == "-f" and value.endswith(".compose.json"):
                overlays.append(json.loads(Path(value).read_text()))
        action, *rest = options
        if action == "config":
            emit({"services": {name: {} for name in state["containers"]}})
        elif action == "ps":
            names = [name for name in state["containers"] if name in rest]
            values = (
                [state["containers"][name] for name in names]
                if names
                else list(state["containers"].values())
            )
            if "--format" in rest:
                assert len(values) == 1
                emit({"State": "running", "Health": "healthy"})
            else:
                emit("\n".join(value["Id"] for value in values))
        elif action == "build":
            service = rest[-1]
            settings = overlays[-1]["services"][service]
            build_id = rest[rest.index("--build-arg") + 1].removeprefix("BUILD_ID=")
            identity = (
                "sha256:"
                + hashlib.sha256((service + settings["image"]).encode()).hexdigest()
            )
            image = {"Id": identity, "Config": {"Env": ["BUILD_ID=" + build_id]}}
            state["images"][identity] = state["images"][settings["image"]] = image
            state["build_ids"][identity] = build_id
            state["builds"].append(service)
        elif action == "up":
            assert "--no-build" in rest and "--no-deps" in rest and "never" in rest
            service = rest[-1]
            value = state["containers"][service]
            identity = overlays[-1]["services"][service]["image"]
            new_id = hashlib.sha256(
                (service + identity + "replacement").encode()
            ).hexdigest()
            value.update(Id=new_id, Image=identity)
            value["Config"].update(Image=identity, Hostname=new_id[:12])
            value["Config"]["Env"] = [
                (
                    "BUILD_ID=" + state["build_ids"][identity]
                    if item.startswith("BUILD_ID=")
                    else item
                )
                for item in value["Config"]["Env"]
            ]
            value["Config"]["Labels"]["com.docker.compose.config-hash"] = "replacement"
            value["State"].update(
                Pid=value["State"]["Pid"] + 100, StartedAt="fixture-replacement"
            )
            state["switches"].append(service)
        elif action == "exec":
            assert "app.scripts.validate_deployment_chat" in rest
            body = json.load(sys.stdin)
            assert body["routing_action"] == "auto_send" and body["sources"]
            assert body["requires_human"] is False and "Bisq" in body["answer"]
            state["synthetic_validator_calls"] += 1
            emit("chat_smoke=direct_answer_verified")
        else:
            raise AssertionError(("unknown compose", options))
    else:
        raise AssertionError(("unknown docker", args))


def curl():
    url = args[-1]
    if url.startswith("https://api.github.com/"):
        emit(
            {
                "workflow_runs": [
                    {
                        "head_sha": state["candidate"],
                        "event": "workflow_dispatch",
                        "head_branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                        "run_number": 1,
                        "run_attempt": 1,
                    }
                ]
            }
        )
    elif "-X" in args:
        payload = json.loads(args[args.index("-d") + 1])
        kind = "live_mcp" if "current BTC" in payload["question"] else "standard"
        state["provider_calls"].append(kind)
        save()
        if state["scenario"] == "lost_smoke" and kind == "standard":
            pid = os.getppid()
            for _ in range(20):
                command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
                if b"deploy_release_host.py" in command_line:
                    state["killed_owner_pid"] = pid
                    save()
                    os.kill(pid, signal.SIGKILL)
                    raise SystemExit(55)
                tail = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2].split()
                pid = int(tail[1])
            raise AssertionError("fixture owner ancestor not found")
        emit(
            {
                "answer": "Bisq supports bitcoin trade with the seller in this synthetic fixture.",
                "sources": [{"content": "Synthetic public fixture evidence"}],
                "response_time": 0.01,
                "requires_human": False,
                "routing_action": "auto_send",
                "mcp_tools_used": [
                    {"tool": "get_market_prices", "result": "Synthetic fixture result"}
                ],
            }
        )
        print("200")
    elif url.endswith("/api/health"):
        emit({"build_id": state["build_ids"][state["containers"]["api"]["Image"]]})
    elif url.endswith("/login"):
        emit(
            "<html>"
            + state["build_ids"][state["containers"]["web"]["Image"]]
            + "</html>"
        )
    else:
        raise AssertionError(("unknown curl", args))


try:
    if command == "docker":
        docker()
    elif command == "curl":
        curl()
    elif command == "git":
        if "ls-remote" in args:
            print(state["candidate"] + "\t" + args[-1])
        else:
            save()
            os.execv(state["real_git"], [state["real_git"], *args])
    else:
        raise AssertionError("unknown boundary executable")
finally:
    save()
