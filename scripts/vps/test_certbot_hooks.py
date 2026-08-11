import unittest
from pathlib import Path


VPS_DIR = Path(__file__).resolve().parent


class CertbotHookTests(unittest.TestCase):
    def test_hooks_use_fixed_root_owned_inputs(self):
        for name in ("certbot_pre_renew.sh", "certbot_post_renew.sh"):
            script = (VPS_DIR / name).read_text(encoding="utf-8")
            self.assertIn("deploy_dir=/opt/edgeathlete", script)
            self.assertIn('require_root_owned "$deploy_dir"', script)
            self.assertIn('require_root_owned "$compose_file"', script)
            self.assertIn('require_root_owned "$env_file"', script)
            self.assertIn('[ -L "$path" ]', script)
            self.assertIn("0022", script)
            self.assertNotIn("EDGEATHLETE_DEPLOY_DIR", script)

    def test_post_hook_restarts_only_nginx_and_checks_public_health(self):
        script = (VPS_DIR / "certbot_post_renew.sh").read_text(encoding="utf-8")
        self.assertIn("up -d --no-deps vps-nginx", script)
        self.assertIn("exec -T vps-nginx nginx -t", script)
        self.assertIn('https://$domain/api/health/', script)

    def test_systemd_runs_post_check_after_certbot(self):
        override = (VPS_DIR / "certbot.service.d.conf").read_text(encoding="utf-8")
        self.assertEqual(
            override,
            "[Service]\nExecStopPost=/etc/letsencrypt/renewal-hooks/post/edgeathlete-nginx\n",
        )


if __name__ == "__main__":
    unittest.main()
