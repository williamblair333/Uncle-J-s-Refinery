"""features/dcup/dcup_guard.py — the PreToolUse hook that keeps docker port claims on dcup.

The matrix is the contract: BLOCKED commands claim a fixed host port outside the registry
(including the trivial spelling variants an agent might reach for); ALLOWED commands are
read-only docker use, dcup itself, and text that only mentions the blocked commands.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "features" / "dcup" / "dcup_guard.py"
_spec = importlib.util.spec_from_file_location("dcup_guard", GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

BLOCKED = [
    # compose up, every spelling
    "docker compose up",
    "docker compose up -d",
    "docker compose -f x.yml up",
    "docker compose -f x.yml -p proj up -d --build",
    "docker compose --file=x.yml up",
    "docker compose --project-directory /srv/app up -d",
    "docker --context remote compose up",
    "docker -H unix:///var/run/docker.sock compose up -d",
    "docker-compose up",
    "docker-compose -f a.yml up -d",
    "/usr/bin/docker compose up",
    "/usr/local/bin/docker-compose up -d",
    "docker compose create",
    "docker compose run --service-ports web",
    "docker compose run -p 8080:80 web",
    "docker compose run --publish=8080:80 web",
    # wrappers and prefixes
    "sudo docker compose up -d",
    "sudo -E docker compose up",
    "sudo -u bill docker compose up",
    "sudo -- docker compose up",
    "DOCKER_HOST=unix:///x docker compose up",
    "FOO=1 BAR=2 docker-compose up",
    "env docker compose up",
    "env -i PATH=/usr/bin docker compose up",
    "env -u FOO docker compose up",
    "nohup docker compose up -d &",
    "timeout 60 docker compose up",
    "timeout -s KILL 60 docker compose up",
    "nice -n 10 docker compose up",
    "time docker compose up",
    "exec docker compose up",
    "command docker compose up",
    "\\docker compose up",
    "d''ocker compose up",
    '"docker" compose up',
    "doc\\ker compose up",
    "stdbuf -oL docker compose up",
    "flock /tmp/l docker compose up",
    "flock -c 'docker compose up' /tmp/l",
    "watch -n 5 docker compose up",
    "sudo env FOO=1 nice docker compose up -d",
    # command lists, pipes, substitutions
    "cd /opt/x && docker compose up -d",
    "cd /opt/x; docker compose up -d",
    "false || docker compose up",
    "docker compose pull\ndocker compose up -d",
    "docker compose up -d | tee log",
    "echo $(docker compose up -d)",
    'echo "$(docker compose up -d)"',
    "echo `docker compose up -d`",
    "( docker compose up -d )",
    "{ docker compose up -d; }",
    "if true; then docker compose up -d; fi",
    "for i in 1; do docker compose up -d; done",
    "cat <(docker compose up)",
    # shells and eval
    "bash -c 'docker compose up -d'",
    "sh -c \"docker compose up\"",
    "bash -lc 'cd /x && docker compose up -d'",
    "sudo bash -c 'docker compose up'",
    "eval 'docker compose up'",
    "eval docker compose up",
    "su -c 'docker compose up' bill",
    "env -S 'docker compose up'",
    "bash -c \"bash -c 'docker compose up'\"",
    "bash <<'EOF'\ndocker compose up -d\nEOF",
    "sh <<< 'docker compose up'",
    "echo 'docker compose up -d' | bash",
    "printf 'docker compose up' | sudo sh",
    "cat <<EOF\n$(docker compose up)\nEOF",
    "echo up | xargs docker compose",
    "D=docker; $D compose up -d",
    # docker run / create with a fixed host port
    "docker run -p 8080:80 nginx",
    "docker run -d -p 8080:80 nginx",
    "docker run -p 127.0.0.1:8080:80 nginx",
    "docker run -p 8080:80/udp nginx",
    "docker run -p [::1]:8080:80 nginx",
    "docker run -p 8000-8010:8000-8010 nginx",
    "docker run --publish 8080:80 nginx",
    "docker run --publish=8080:80 nginx",
    "docker run -p8080:80 nginx",
    "docker run -dp 8080:80 nginx",
    "docker run -itp 8080:80 nginx",
    "docker run --rm --name x -e A=1 -v /a:/b -p 8080:80 nginx",
    "docker run -p $PORT:80 nginx",
    "docker run --publish published=8080,target=80 nginx",
    "docker container run -p 8080:80 nginx",
    "docker create -p 8080:80 nginx",
    "docker container create -p 8080:80 nginx",
    "sudo docker run -p 8080:80 nginx",
    "sudo -E docker run -d -p 9000:9000 portainer/portainer-ce",
    "DOCKER_HOST=x docker run -p 80:80 nginx",
    "docker --context x run -p 80:80 nginx",
    "docker run --some-new-bool-flag -p 8080:80 nginx",
    "docker run -X -p 8080:80 nginx",
    "docker run --gpus all -p 8080:80 nginx",
    # dcup's own escape hatch
    "dcup --bypass up -d",
    "dcup --bypass -f x.yml up",
]

ALLOWED = [
    # read-only docker
    "docker ps",
    "docker ps -a --format '{{.Names}}\t{{.Ports}}'",
    "docker compose ps",
    "docker compose ls -a",
    "docker compose logs -f web",
    "docker compose config",
    "docker compose -f x.yml config --format json",
    "docker compose version",
    "docker compose down",
    "docker compose stop",
    "docker compose start",
    "docker compose restart web",
    "docker compose pull",
    "docker compose build",
    "docker compose exec web sh",
    "docker compose run --rm web pytest",
    "docker compose up --help",
    "docker compose --dry-run up -d",
    "docker compose",
    "docker-compose ps",
    "docker logs gitea",
    "docker inspect gitea",
    "docker images",
    "docker events --filter type=container",
    "docker stats --no-stream",
    "docker exec -it gitea sh",
    "docker stop x",
    "docker rm x",
    "docker pull nginx",
    "docker build -t x .",
    "docker network ls",
    "docker port gitea",
    # docker run without a fixed host port
    "docker run --rm alpine echo hi",
    "docker run --rm -it alpine sh",
    "docker run -P nginx",
    "docker run --publish-all nginx",
    "docker run -p 80 nginx",
    "docker run -p 127.0.0.1::80 nginx",
    "docker run --rm alpine ls -p",
    "docker run --rm alpine sh -c 'nc -l -p 8080'",
    "docker run --rm -e P=1 alpine",
    "docker run --rm --network host curlimages/curl http://127.0.0.1:8090/health",
    # dcup itself
    "dcup up -d",
    "dcup -f compose.yaml up -d",
    "dcup --check-only -f x.yml",
    "dcup list",
    "dcup release kanka-ce",
    "dcup scan /opt/proj",
    "dcup --bypass ps",
    "just heretic up",
    # text that only mentions the commands
    "echo 'docker compose up'",
    "echo docker compose up",
    "grep -rn 'docker compose up' docs/",
    "grep -n \"docker run -p\" README.md",
    "git commit -F - <<'EOF'\nfix: block docker compose up and docker run -p 8080:80\nEOF",
    "cat > notes.md <<'EOF'\nRun docker compose up -d here.\nEOF",
    "cat <<EOF\ndocker compose up\nEOF",
    "printf 'docker compose up\\n' > notes.txt",
    "# docker compose up\nls",
    "ls  # then docker compose up",
    "command -v docker",
    "which docker-compose",
    "man docker-compose",
    "docker compose ps | grep up",
    "docker ps | grep 'Up 6 hours'",
    "ss -ltnp | grep 8080",
    "ls -la",
    "",
]


@pytest.mark.parametrize("cmd", BLOCKED)
def test_blocked(cmd):
    assert guard.analyze(cmd), f"should block: {cmd!r}"


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd):
    assert guard.analyze(cmd) == [], f"should allow: {cmd!r}"


@pytest.mark.parametrize("spec,fixed", [
    ("8080:80", True), ("127.0.0.1:8080:80", True), ("8080:80/tcp", True),
    ("[::1]:8080:80", True), ("0.0.0.0:53:53/udp", True), ("=8080:80", True),
    ("80", False), ("80/udp", False), ("127.0.0.1::80", False), ("", False),
    ("published=8080,target=80", True), ("target=80", False),
])
def test_fixed_host_port(spec, fixed):
    assert guard.fixed_host_port(spec) is fixed


def _run_hook(payload, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "DCUP_GUARD"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)


def test_hook_blocks_with_exit_2_and_reason():
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "docker compose up -d"}})
    assert r.returncode == 2
    assert "dcup up" in r.stderr


def test_hook_allows_read_only():
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "docker compose ps"}})
    assert r.returncode == 0
    assert r.stderr == ""


def test_hook_ignores_other_tools_and_bad_input():
    assert _run_hook({"tool_name": "Edit", "tool_input": {"command": "docker compose up"}}).returncode == 0
    r = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0


def test_kill_switch_is_hook_env_only():
    payload = {"tool_name": "Bash", "tool_input": {"command": "docker compose up"}}
    assert _run_hook(payload, {"DCUP_GUARD": "off"}).returncode == 0
    # The same switch written into the command itself changes nothing.
    inline = {"tool_name": "Bash", "tool_input": {"command": "DCUP_GUARD=off docker compose up"}}
    assert _run_hook(inline).returncode == 2


def test_internal_error_fails_open(monkeypatch, capsys):
    def boom(_cmd, depth=0):
        raise RuntimeError("bug")
    monkeypatch.setattr(guard, "analyze", boom)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": staticmethod(
        lambda: json.dumps({"tool_name": "Bash", "tool_input": {"command": "docker compose up"}}))})())
    monkeypatch.setattr(guard, "_log", lambda line: None)
    assert guard.main() == 0
    assert "internal error" in capsys.readouterr().err
