import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from validate_workflow_paths import checked_file

class WorkflowSafetyTests(unittest.TestCase):
    def test_untrusted_workflow_input_is_literal_argument(self):
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/publish-vk.yml').read_text()
        block=source.split('        run: |',1)[1]
        script='\n'.join(line[10:] for line in block.splitlines() if line.strip())
        script=script.replace('python validate_workflow_paths.py', 'python '+str(Path(__file__).resolve().parents[1]/'validate_workflow_paths.py'))
        script=script.replace('python vk_publish.py', "printf '%s\\n'")
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'injected'
            payload='$(touch '+str(marker)+')'
            result=subprocess.run(['bash','-c',script],cwd=tmp,env={**os.environ,'TEXT_FILE':payload,'IMAGE_PATH':'','DRY_RUN':'true'},capture_output=True,text=True)
            self.assertFalse(marker.exists())
            self.assertNotEqual(result.returncode,0)

    def test_normal_repository_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'post.txt';path.write_text('Approved text')
            self.assertEqual(checked_file(Path(tmp),'post.txt',{'.txt'}),path)

    def test_credentials_and_external_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('.git/config','../outside.txt','/etc/passwd'):
                with self.subTest(path=path),self.assertRaises(ValueError):checked_file(Path(tmp),path,{'.txt','.md'})

if __name__=='__main__':unittest.main()
