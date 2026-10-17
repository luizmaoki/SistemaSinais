"""Start and verify the separate local OIDC stack, preserving all volumes."""
import argparse
import json
import secrets
import urllib.error
import urllib.request

from docker_utils import ROOT, run_compose

ENV_FILE = ROOT / ".env.oidc.local"
COMMAND = ["docker", "compose", "--project-name", "capitaloidc", "--file", str(ROOT / "docker-compose.yml"),
           "--file", str(ROOT / "infra/docker/compose.oidc.yml"), "--env-file", str(ENV_FILE)]


def prepare_environment():
    # Exclusive creation never replaces an operator's existing credentials.
    if not ENV_FILE.exists():
        with ENV_FILE.open("x", encoding="utf-8") as stream:
            stream.write("KEYCLOAK_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
        ENV_FILE.chmod(0o600)


def read_json(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def check():
    issuer = "http://localhost:18080/realms/capital"
    metadata = read_json(issuer + "/.well-known/openid-configuration")
    if metadata["issuer"] != issuer or "S256" not in metadata["code_challenge_methods_supported"]:
        raise RuntimeError("Keycloak issuer/PKCE mismatch")
    config = read_json("http://localhost:13000/api/v1/auth/config")
    if config["auth_mode"] != "oidc" or not config["configured"] or config["demo_available"]:
        raise RuntimeError("Application did not enable OIDC exclusively")
    try:
        read_json("http://localhost:13000/api/v1/auth/session")
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
    else:
        raise RuntimeError("Anonymous session was accepted in OIDC mode")
    print("OIDC CONFIG OK: exact issuer, S256, no anonymous/demo fallback")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "check", "down"])
    args = parser.parse_args()
    prepare_environment()
    if args.action == "up":
        run_compose(COMMAND, "up", "--build", "-d", "--wait", "--wait-timeout", "360")
        check()
        print("Open http://localhost:13000/login")
    elif args.action == "check":
        check()
    else:
        # No --volumes: preserves identities, sessions and user data.
        run_compose(COMMAND, "down")


if __name__ == "__main__":
    main()
