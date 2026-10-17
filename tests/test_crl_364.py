"""Real OpenSSL signing/verification in an isolated temporary directory."""
import subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import crl_sync
class CrlTests(unittest.TestCase):
    def test_only_valid_signed_monotonic_crl_is_installed(self):
        def run(*args):subprocess.run(list(args),check=True,capture_output=True,timeout=20)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'index').write_text('');(root/'serial').write_text('1000\n');(root/'crlnumber').write_text('1000\n');(root/'certs').mkdir()
            run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'ca.key'),'-out',str(root/'ca.crt'),'-days','2','-subj','/CN=Beeny-test-CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
            cfg=root/'openssl.cnf';cfg.write_text(f'[ca]\ndefault_ca=local\n[local]\ndatabase={root}/index\nnew_certs_dir={root}/certs\ncertificate={root}/ca.crt\nprivate_key={root}/ca.key\nserial={root}/serial\ncrlnumber={root}/crlnumber\ndefault_md=sha256\ndefault_crl_days=1\npolicy=policy\n[policy]\ncommonName=supplied\n')
            run('openssl','ca','-gencrl','-batch','-config',str(cfg),'-out',str(root/'first.pem'))
            vpn=root/'server.conf';vpn.write_text(f'ca {root}/ca.crt\ncrl-verify {root}/deployed.pem\n')
            first=(root/'first.pem').read_text()
            with patch.object(crl_sync,'VPN_ROOT',root):
                self.assertTrue(crl_sync.install_crl(first,vpn)['success'])
                self.assertTrue(crl_sync.install_crl(first,vpn)['success'])
                self.assertEqual((root/'deployed.pem').stat().st_mode&0o777,0o644)
                with self.assertRaises(Exception):crl_sync.install_crl('-----BEGIN X509 CRL-----\n'+'invalid'*50+'\n-----END X509 CRL-----',vpn)
                self.assertEqual((root/'deployed.pem').read_text(),first)
                run('openssl','ca','-gencrl','-batch','-config',str(cfg),'-out',str(root/'second.pem'))
                second=(root/'second.pem').read_text();crl_sync.install_crl(second,vpn)
                with self.assertRaises(ValueError):crl_sync.install_crl(first,vpn)
                self.assertEqual((root/'deployed.pem').read_text(),second)
