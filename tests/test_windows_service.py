import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import subprocess
import windows_service as service


class WindowsLauncherTest(unittest.TestCase):
    def test_process_matching_requires_exact_project_interpreter_and_script(self):
        root=r'C:\Projects\邮箱 app'
        python=root+r'\.venv\Scripts\python.exe'
        script=root+r'\web_ui.py'
        processes=[{'ProcessId':i,'ExecutablePath':exe,'CommandLine':str(i)}
                   for i,exe in [(1,python),(2,python),(3,r'C:\Python\python.exe'),(4,python),(5,python)]]
        commands={'1':[python,'-u',script,'--port','5050'],
                  '2':[python,'-u',script+'.backup'],
                  '3':[r'C:\Python\python.exe',script],
                  '4':[python,'-c','print("'+script+'")'],
                  '5':[python,'web_ui.py']}
        self.assertEqual(service.project_process_ids(processes,root,commands.__getitem__),[1])
        self.assertEqual(service.project_process_ids(processes,root.upper(),commands.__getitem__),[1])

    def test_restart_uses_pid_tree_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);python=root/'.venv'/'Scripts'/'python.exe'
            python.parent.mkdir(parents=True);python.touch()
            with patch.object(service,'ROOT',root), patch.object(service.os,'name','nt'), \
                 patch.object(service,'running_processes',return_value=[]), \
                 patch.object(service,'project_process_ids',return_value=[123]), \
                 patch.object(service.subprocess,'run') as stop, \
                 patch.object(service.subprocess,'call',return_value=0) as start:
                self.assertEqual(service.main(['restart','--port','8080']),0)
                stop.assert_called_once_with(['taskkill.exe','/PID','123','/T','/F'],check=True)
                command=start.call_args.args[0]
                self.assertEqual(command[0],str(python))
                self.assertEqual(command[2],str(root/'web_ui.py'))
                self.assertEqual(command[-2:],['--port','8080'])
                self.assertEqual(start.call_args.kwargs['cwd'],root)

    def test_start_does_not_duplicate_existing_project(self):
        with patch.object(service.os,'name','nt'), patch.object(Path,'is_file',return_value=True), \
             patch.object(service,'running_processes',return_value=[]), \
             patch.object(service,'project_process_ids',return_value=[123]), \
             patch.object(service.subprocess,'call') as start:
            self.assertEqual(service.main(['start']),0)
            start.assert_not_called()

    def test_process_discovery_error_does_not_start_another_server(self):
        with patch.object(service.os,'name','nt'), patch.object(Path,'is_file',return_value=True), \
             patch.object(service,'running_processes',side_effect=subprocess.CalledProcessError(1,'powershell')), \
             patch.object(service.subprocess,'call') as start:
            self.assertEqual(service.main(['restart']),1)
            start.assert_not_called()

    def test_discovery_supports_single_process_and_empty_output(self):
        process={'ProcessId':123,'ExecutablePath':'python.exe','CommandLine':'test'}
        for output,expected in [(json.dumps(process),[process]),('',[])]:
            with patch.object(service.subprocess,'run',return_value=Mock(stdout=output)):
                self.assertEqual(service.running_processes(),expected)
