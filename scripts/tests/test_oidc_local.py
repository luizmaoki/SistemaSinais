import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oidc_local


class OidcLocalTests(unittest.TestCase):
    def test_local_admin_secret_is_created_once_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env.oidc.local"
            with patch.object(oidc_local, "ENV_FILE", target):
                oidc_local.prepare_environment()
                content = target.read_text()
                self.assertTrue(content.startswith("KEYCLOAK_ADMIN_PASSWORD="))
                self.assertGreater(len(content.partition("=")[2].strip()), 32)
                target.write_text("KEYCLOAK_ADMIN_PASSWORD=operator-configured\n")
                oidc_local.prepare_environment()
                self.assertEqual(target.read_text(), "KEYCLOAK_ADMIN_PASSWORD=operator-configured\n")

    def test_fixture_requires_pkce_and_exact_redirect(self):
        fixture = json.loads((oidc_local.ROOT / "infra/keycloak/capital-realm.json").read_text(encoding="utf-8-sig"))
        client = fixture["clients"][0]
        self.assertEqual(client["redirectUris"], ["http://localhost:13000/api/v1/auth/callback"])
        self.assertEqual(client["attributes"]["pkce.code.challenge.method"], "S256")
        self.assertFalse(client["directAccessGrantsEnabled"])
        self.assertFalse(client["implicitFlowEnabled"])


if __name__ == "__main__":
    unittest.main()
