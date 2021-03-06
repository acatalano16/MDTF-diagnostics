import os
import sys
import glob
import shutil
import timeit
from abc import ABCMeta, abstractmethod
if os.name == 'posix' and sys.version_info[0] < 3:
    try:
        import subprocess32 as subprocess
    except (ImportError, ModuleNotFoundError):
        import subprocess
else:
    import subprocess
import util

class EnvironmentManager(object):
    # analogue of TestSuite in xUnit - abstract base class
    __metaclass__ = ABCMeta

    def __init__(self, config, verbose=0):
        self.test_mode = config['envvars']['test_mode']
        self.pods = []
        self.envs = set()

    # -------------------------------------
    # following are specific details that must be implemented in child class 

    @abstractmethod
    def create_environment(self, env_name):
        pass 

    @abstractmethod
    def set_pod_env(self, pod):
        pass 

    @abstractmethod
    def activate_env_command(self, pod):
        pass 

    @abstractmethod
    def deactivate_env_command(self, pod):
        pass 

    @abstractmethod
    def destroy_environment(self, env_name):
        pass 

    # -------------------------------------

    def setUp(self):
        for pod in self.pods:
            self.set_pod_env(pod)
            self.envs.add(pod.env)
        for env in self.envs:
            self.create_environment(env)

    # -------------------------------------

    def run(self, verbose=0):
        for pod in self.pods:
            # Find and confirm POD driver script , program (Default = {pod_name,driver}.{program} options)
            # Each pod could have a settings files giving the name of its driver script and long name
            if verbose > 0: print("--- MDTF.py Starting POD "+pod.name+"\n")

            pod.setUp()
            # skip this pod if missing data
            if pod.missing_files != []:
                continue

            pod.logfile_obj = open(os.path.join(pod.POD_WK_DIR, pod.name+".log"), 'w')

            run_command = pod.run_command()          
            if self.test_mode:
                run_command = 'echo "TEST MODE: would call {}"'.format(run_command)
            commands = [
                self.activate_env_command(pod), pod.validate_command(), 
                run_command, self.deactivate_env_command(pod)
                ]
            # '&&' so we abort if any command in the sequence fails.
            commands = ' && '.join([s for s in commands if s])
 
            print("Calling :  "+run_command) # This is where the POD is called #
            print('Will run in env: '+pod.env)
            start_time = timeit.default_timer()
            try:
                # Need to run bash explicitly because 'conda activate' sources 
                # env vars (can't do that in posix sh). tcsh could also work.
                pod.process_obj = subprocess.Popen(
                    ['bash', '-c', commands],
                    env = os.environ, 
                    cwd = pod.POD_WK_DIR,
                    stdout = pod.logfile_obj, stderr = subprocess.STDOUT)
            except OSError as e:
                print('ERROR :',e.errno,e.strerror)
                print(" occured with call: " +run_command)

        # if this were python3 we'd have asyncio, instead wait for each process
        # to terminate and close all log files
        for pod in self.pods:
            if pod.process_obj is not None:
                pod.process_obj.wait()
                pod.process_obj = None
            if pod.logfile_obj is not None:
                pod.logfile_obj.close()
                pod.logfile_obj = None

    # -------------------------------------

    def tearDown(self):
        # call diag's tearDown to clean up
        for pod in self.pods:
            pod.tearDown()
        for env in self.envs:
            self.destroy_environment(env)


class NoneEnvironmentManager(EnvironmentManager):
    # Do not attempt to switch execution environments for each POD.
    def create_environment(self, env_name):
        pass 
    
    def destroy_environment(self, env_name):
        pass 

    def set_pod_env(self, pod):
        pass

    def activate_env_command(self, pod):
        return ''

    def deactivate_env_command(self, pod):
        return '' 


class CondaEnvironmentManager(EnvironmentManager):
    # Use Anaconda to switch execution environments.

    def __init__(self, config, verbose=0):
        super(CondaEnvironmentManager, self).__init__(config, verbose)

        if ('conda_env_root' in config['settings']) and \
            (os.path.isdir(config['settings']['conda_env_root'])):
            # need to resolve relative path
            cwd = os.getcwd()
            paths = util.PathManager()
            os.chdir(os.path.join(paths.CODE_ROOT, 'src'))
            self.conda_env_root = os.path.realpath(config['settings']['conda_env_root'])
            os.chdir(cwd)
        else:
            self.conda_env_root = os.path.join(
                subprocess.check_output('conda info --root', shell=True),
                'envs' # only true in default install, need to fix
            ) 

    def create_environment(self, env_name):
        # check to see if conda env exists, and if not, try to create it
        conda_prefix = os.path.join(self.conda_env_root, env_name)
        test = subprocess.call(
            'conda env list | grep -qF "{}"'.format(conda_prefix), 
            shell=True
        )
        if test != 0:
            print 'Conda env {} not found; creating it'
            self._call_conda_create(env_name)

    def _call_conda_create(self, env_name):
        paths = util.PathManager()
        prefix = '_MDTF-diagnostics'
        if env_name == prefix:
            short_name = 'base'
        else:
            short_name = env_name[(len(prefix)+1):]
        path = '{}/src/conda_env_{}.yml'.format(paths.CODE_ROOT, short_name)
        if not os.path.exists(path):
            print "Can't find {}".format(path)
        else:
            conda_prefix = os.path.join(self.conda_env_root, env_name)
            print 'Creating conda env {} in {}'.format(env_name, conda_prefix)
        
        commands = \
            'source {}/src/conda_init.sh && '.format(paths.CODE_ROOT) \
                + 'conda env create --force -q -p="{}" -f="{}"'.format(
                conda_prefix, path
            )
        try: 
            subprocess.Popen(['bash', '-c', commands])
        except OSError as e:
            print('ERROR :',e.errno,e.strerror)

    def create_all_environments(self):
        paths = util.PathManager()
        command = '{}/src/conda_env_setup.sh'.format(paths.CODE_ROOT)
        try: 
            subprocess.Popen(['bash', '-c', command])
        except OSError as e:
            print('ERROR :',e.errno,e.strerror)

    def destroy_environment(self, env_name):
        pass 

    def set_pod_env(self, pod):
        keys = [s.lower() for s in pod.required_programs]
        if ('r' in keys) or ('rscript' in keys):
            pod.env = '_MDTF-diagnostics-R'
        elif 'ncl' in keys:
            pod.env = '_MDTF-diagnostics-NCL'
        else:
            pod.env = '_MDTF-diagnostics-python'

    def activate_env_command(self, pod):
        # Source conda_init.sh to set things that aren't set b/c we aren't 
        # in an interactive shell.
        paths = util.PathManager()
        conda_prefix = os.path.join(self.conda_env_root, pod.env)
        return 'source {}/src/conda_init.sh && conda activate {}'.format(
            paths.CODE_ROOT, conda_prefix
            )

    def deactivate_env_command(self, pod):
        return '' 
