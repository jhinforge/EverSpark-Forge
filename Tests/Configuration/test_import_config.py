from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Configuration"))

import import_config  # noqa: E402


TUNNEL_ID = "11111111-2222-3333-4444-555555555555"


def write_tunnel_files(source: Path, env_name: str = "env.txt") -> None:
    (source / env_name).write_text(
        f"CF_TUNNEL_UUID={TUNNEL_ID}\n"
        "CF_HOSTNAME=example.test\n"
        "CF_LOCAL_PORT=8780\n"
        "CF_TUNNEL_NAME=test\n"
        "EVERSPARK_LOG_DIR=/tmp/everspark-logs\n",
        encoding="utf-8",
    )
    (source / f"{TUNNEL_ID}.json").write_text(
        json.dumps(
            {
                "AccountTag": "account",
                "TunnelSecret": "do-not-print-this-secret",
                "TunnelID": TUNNEL_ID,
            }
        ),
        encoding="utf-8",
    )


class ConfigurationImportTests(unittest.TestCase):
    def test_env_txt_and_private_files_are_imported_without_moving_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            (source / "rclone.conf").write_text(
                "[r2-assets]\ntype = s3\nprovider = Cloudflare\n",
                encoding="utf-8",
            )
            result = import_config.import_configuration(source, repo_root=repo)
            values = import_config.parse_env(repo / ".env")
            self.assertEqual(values["EVERSPARK_NETWORK_BACKEND"], "cloudflare")
            self.assertEqual(values["CF_LOCAL_PORT"], "8780")
            self.assertEqual(result["rclone_remotes"], ["r2-assets"])
            self.assertEqual(result["storage_backend"], "local")
            self.assertTrue((source / "env.txt").is_file())
            self.assertTrue((source / "rclone.conf").is_file())
            self.assertTrue((source / f"{TUNNEL_ID}.json").is_file())
            credential = repo / "Data/Configuration/cloudflare" / f"{TUNNEL_ID}.json"
            rclone = repo / "Data/Configuration/rclone/rclone.conf"
            self.assertTrue(credential.is_file())
            self.assertTrue(rclone.is_file())
            self.assertEqual(stat.S_IMODE((repo / ".env").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(rclone.stat().st_mode), 0o600)
            self.assertNotIn("do-not-print-this-secret", import_config._render_result(result))

    def test_dot_env_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source, ".env")
            result = import_config.import_configuration(source, repo_root=repo)
            self.assertTrue(result["environment_source"].endswith("/.env"))

    def test_identical_dot_env_and_env_txt_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            (source / ".env").write_bytes((source / "env.txt").read_bytes())
            import_config.import_configuration(source, repo_root=repo)

    def test_conflicting_environment_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            (source / ".env").write_text("CF_LOCAL_PORT=9999\n", encoding="utf-8")
            with self.assertRaisesRegex(
                import_config.ConfigurationImportError, "different settings"
            ):
                import_config.import_configuration(source, repo_root=repo)

    def test_mismatched_tunnel_credential_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            credential = source / f"{TUNNEL_ID}.json"
            payload = json.loads(credential.read_text(encoding="utf-8"))
            payload["TunnelID"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            credential.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                import_config.ConfigurationImportError, "does not match"
            ):
                import_config.import_configuration(source, repo_root=repo)

    def test_tunnel_must_target_webui(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            env_file = source / "env.txt"
            env_file.write_text(
                env_file.read_text(encoding="utf-8").replace(
                    "CF_LOCAL_PORT=8780", "CF_LOCAL_PORT=8188"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                import_config.ConfigurationImportError, "must match EverSpark WebUI"
            ):
                import_config.import_configuration(source, repo_root=repo)

    def test_relative_explicit_environment_is_resolved_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, repo = root / "source", root / "repo"
            source.mkdir()
            repo.mkdir()
            write_tunnel_files(source)
            result = import_config.import_configuration(
                source, explicit_env="env.txt", repo_root=repo
            )
            self.assertEqual(result["environment_source"], str(source / "env.txt"))


if __name__ == "__main__":
    unittest.main()
