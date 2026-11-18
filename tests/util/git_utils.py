"""git helpers for fetching code from github.trellix.com (hxsim, XClient, ma-sdk-fake)."""
import base64
import os
import subprocess

GITHUB_TRELLIX = "https://github.trellix.com/"


def git_env():
    """Environment for git calls to github.trellix.com that never prompts.

    If XCLIENT_GITHUB_TOKEN is set (a github.trellix.com token with read access;
    a CI secret), it is passed as an http.extraHeader through GIT_CONFIG_* so it
    never appears on a command line. Otherwise git's own credential helper (Git
    Credential Manager) is used -- not available to a runner running as LocalSystem.
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    token = os.environ.get("XCLIENT_GITHUB_TOKEN")
    if token:
        basic = base64.b64encode("x-access-token:{}".format(token).encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.{}.extraHeader".format(GITHUB_TRELLIX),
                   GIT_CONFIG_VALUE_0="Authorization: Basic " + basic)
    return env


def git(*args, env=None, cwd=None):
    """Run git; fail with its output (which never contains the token) on error."""
    p = subprocess.run(["git"] + list(args), env=env or git_env(), cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, "git {} failed (credentials for github.trellix.com: Git Credential Manager " \
        "or XCLIENT_GITHUB_TOKEN):\n{}".format(" ".join(a for a in args if not a.startswith("http"))[:120], out[-1500:])
    return out.strip()
