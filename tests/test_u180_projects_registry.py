"""Registry DATA_ONLY library gate. All writes use isolated temporary fixtures."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path.cwd()))
from v7_harness.coord.projects import enroll, load

SESSION = 'aaaaaaaa-1111-4111-8111-111111111111'

class Registry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root/'home/projects.json'
        self.projects = [self.root/f'project{i}' for i in range(3)]
        for p in self.projects:
            p.mkdir()

    def add(self, project, event, tool='codex', **kwargs):
        return enroll(self.registry, project, tool=tool, session=SESSION, event_id=event, **kwargs)

    def test_three_projects_three_tools_nine_receipts_no_authority(self):
        for i,p in enumerate(self.projects):
            for t in ('codex','claude','antigravity'):
                entry = self.add(p,f'{i}-{t}',t)
                self.assertNotIn('authority', entry)
                self.assertNotIn('conductor', entry)
        data = load(self.registry)
        self.assertEqual(1,data['schema'])
        self.assertEqual(3,len(data['projects']))
        self.assertEqual(9,sum(len(p['events']) for p in data['projects']))

    def test_replay_is_identical_and_conflict_refuses(self):
        self.add(self.projects[0],'same')
        original = self.registry.read_bytes()
        self.add(self.projects[0],'same')
        self.assertEqual(original,self.registry.read_bytes())
        other = self.add(self.projects[1],'same')
        updated = self.registry.read_bytes()
        with self.assertRaises(ValueError):
            self.add(self.projects[0],'same',parent_id=other['id'])
        self.assertEqual(updated,self.registry.read_bytes())

    def test_corrupt_registry_is_preserved(self):
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes(b'{broken')
        with self.assertRaises(ValueError):
            self.add(self.projects[0],'event')
        self.assertEqual(b'{broken',self.registry.read_bytes())

    def test_nested_root_requires_explicit_parent(self):
        parent = self.add(self.projects[0],'parent')
        child = self.projects[0]/'nested'
        child.mkdir()
        with self.assertRaises(ValueError):
            self.add(child,'child-missing-parent')
        result = self.add(child,'child',parent_id=parent['id'])
        self.assertEqual(parent['id'],result['parent_id'])

    def test_invalid_tool_session_path_never_changes_registry(self):
        for tool,session in (('unknown',SESSION),('codex','../*')):
            with self.assertRaises(ValueError):
                enroll(self.registry,self.projects[0],tool=tool,session=session,event_id='bad')
        with self.assertRaises(ValueError):
            self.add(self.root/'missing','missing')
        self.assertFalse(self.registry.exists())

    def test_eight_real_processes_lose_no_registrations(self):
        roots = [self.root/f'parallel{i}' for i in range(8)]
        for p in roots:
            p.mkdir()
        procs = [subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(self.registry),
            str(p),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i,p in enumerate(roots)]
        for proc in procs:
            out,err=proc.communicate(timeout=20)
            self.assertEqual(0,proc.returncode,(out,err))
        self.assertEqual(8,len(load(self.registry)['projects']))

    def test_lock_timeout_then_reacquisition(self):
        self.registry.parent.mkdir(parents=True)
        proc = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--hold',str(self.registry)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual('LOCKED',proc.stdout.readline().strip())
        try:
            with self.assertRaises(TimeoutError):
                self.add(self.projects[0],'blocked',timeout_s=0.1)
        finally:
            out,err=proc.communicate('release\n',timeout=10)
            self.assertEqual(0,proc.returncode,(out,err))
        self.add(self.projects[0],'after-release')
        self.assertEqual(1,len(load(self.registry)['projects']))

    def test_valid_json_with_wrong_schema_is_preserved(self):
        self.registry.parent.mkdir(parents=True)
        wrong = b'{"schema":999,"generation":0,"projects":[]}'
        self.registry.write_bytes(wrong)
        with self.assertRaises(ValueError):
            load(self.registry)
        self.assertEqual(wrong,self.registry.read_bytes())

    def test_separate_registries_stay_separate(self):
        self.add(self.projects[0],'one')
        other = self.root/'other/projects.json'
        enroll(other,self.projects[1],tool='claude',session=SESSION,event_id='two')
        self.assertEqual(1,len(load(self.registry)['projects']))
        self.assertEqual(1,len(load(other)['projects']))
        self.assertNotEqual(load(self.registry)['projects'][0]['id'],load(other)['projects'][0]['id'])

    def test_schema_bool_and_float_are_invalid(self):
        self.registry.parent.mkdir(parents=True)
        for value in (True,1.0):
            content = json.dumps({'schema':value,'generation':0,'projects':[]}).encode('utf-8')
            self.registry.write_bytes(content)
            with self.assertRaises(ValueError):
                load(self.registry)
            self.assertEqual(content,self.registry.read_bytes())

    def test_cleanup_failure_still_unlocks_and_closes(self):
        from v7_harness.coord import projects
        with mock.patch.object(projects.os,'replace',side_effect=OSError('replace injected failure')), \
                mock.patch.object(Path,'unlink',side_effect=PermissionError('cleanup injected failure')):
            with self.assertRaises(OSError):
                self.add(self.projects[0],'failure')
        self.add(self.projects[0],'after-failure',timeout_s=0.2)
        self.assertEqual(1,len(load(self.registry)['projects']))

if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':
        enroll(Path(sys.argv[2]),Path(sys.argv[3]),tool='codex',session=SESSION,event_id='parallel-'+sys.argv[4])
    elif len(sys.argv)>1 and sys.argv[1]=='--hold':
        import os
        from v7_harness.coord.stream import _try_lock, _unlock
        fd = os.open(sys.argv[2]+'.lock',os.O_CREAT|os.O_RDWR,0o600)
        if not _try_lock(fd):
            raise RuntimeError('fixture lock unavailable')
        try:
            print('LOCKED',flush=True)
            sys.stdin.readline()
        finally:
            _unlock(fd)
            os.close(fd)
    else:
        unittest.main()
