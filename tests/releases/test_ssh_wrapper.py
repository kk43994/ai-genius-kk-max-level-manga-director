import importlib.util
from pathlib import Path
import shlex
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('ssh_release_wrapper',Path(__file__).resolve().parents[2]/'deploy/ssh-release.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)

class SshWrapperTest(unittest.TestCase):
    def test_ssh_argument_quoting_preserves_literal_metacharacters(self):
        args=['python3','/srv/asset-lab-customer/tools/a/release.py','--origin','https://example.test/$(do-not-execute);x']
        with patch.object(module.subprocess,'run') as run:
            module.ssh(args)
            command=run.call_args.args[0]
            self.assertEqual(command[:2],['ssh','-o'])
            self.assertIn('kelao',command)
            self.assertEqual(shlex.split(command[-1]),args)
            self.assertNotIn('shell',run.call_args.kwargs)

if __name__=='__main__':unittest.main()
