"""Common functions and classes used in multiple places in the MDTF code.
"""

import os
import sys
import glob
import yaml

class _Singleton(type):
    """Private metaclass that creates a :class:`~util.Singleton` base class when
    called. This version is copied from <https://stackoverflow.com/a/6798042>_ and
    should be compatible with both Python 2 and 3.
    """
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

class Singleton(_Singleton('SingletonMeta', (object,), {})): 
    """Parent class defining the 
    `Singleton <https://en.wikipedia.org/wiki/Singleton_pattern>`_ pattern. We
    use this as safer way to pass around global state.

    Note:
        All child classes, :class:`~util.PathManager` and :class:`~util.VariableTranslator`,
        are read-only, although this is not enforced. This eliminates most of the
        danger in using Singletons or global state in general.
    """
    @classmethod
    def _reset(cls):
        """Private method of all :class:`~util.Singleton`-derived classes added
        for use in unit testing only. Calling this method on test teardown 
        deletes the instance, so that tests coming afterward will initialize the 
        :class:`~util.Singleton` correctly, instead of getting the state set 
        during previous tests.
        """
        if cls in cls._instances:
            del cls._instances[cls]


class PathManager(Singleton):
    """:class:`~util.Singleton` holding root paths for the MDTF code. These are
    set in the ``paths`` section of ``config.yml``.
    """
    _root_pathnames = [
        'CODE_ROOT', 'OBS_DATA_ROOT', 'MODEL_DATA_ROOT',
        'WORKING_DIR', 'OUTPUT_DIR'
    ]

    def __init__(self, arg_dict={}, unittest_flag=False):
        for var in self._root_pathnames:
            if unittest_flag: # use in unit testing only
                self.__setattr__(var, 'TEST_'+var)
            else:
                assert var in arg_dict, \
                    'Error: {} not initialized.'.format(var)
                self.__setattr__(var, arg_dict[var])

    def modelPaths(self, case):
        d = {}
        d['MODEL_DATA_DIR'] = os.path.join(self.MODEL_DATA_ROOT, case.case_name)
        case_wk_dir = 'MDTF_{}_{}_{}'.format(case.case_name, case.firstyr, case.lastyr)
        d['MODEL_WK_DIR'] = os.path.join(self.WORKING_DIR, case_wk_dir)
        return d

    def podPaths(self, pod):
        d = {}
        d['POD_CODE_DIR'] = os.path.join(self.CODE_ROOT, 'diagnostics', pod.name)
        d['POD_OBS_DATA'] = os.path.join(self.OBS_DATA_ROOT, pod.name)
        if 'MODEL_WK_DIR' in pod.__dict__:
            d['POD_WK_DIR'] = os.path.join(pod.MODEL_WK_DIR, pod.name)
        return d


class BiDict(dict):
    """Extension of the :obj:`dict` class that allows doing dictionary lookups 
    from either keys or values. 
    
    Syntax for lookup from keys is unchanged, ``bd['key'] = 'val'``, while lookup
    from values is done on the `inverse` attribute and returns a list of matching
    keys if more than one match is present: ``bd.inverse['val'] = ['key1', 'key2']``.    
    See <https://stackoverflow.com/a/21894086>_.
    """
    def __init__(self, *args, **kwargs):
        """Initialize :class:`~util.BiDict` by passing an ordinary :obj:`dict`.
        """
        super(BiDict, self).__init__(*args, **kwargs)
        self.inverse = {}
        for key, value in self.items():
            self.inverse.setdefault(value,[]).append(key) 

    def __setitem__(self, key, value):
        if key in self:
            self.inverse[self[key]].remove(key) 
        super(BiDict, self).__setitem__(key, value)
        self.inverse.setdefault(value,[]).append(key)        

    def __delitem__(self, key):
        self.inverse.setdefault(self[key],[]).remove(key)
        if self[key] in self.inverse and not self.inverse[self[key]]: 
            del self.inverse[self[key]]
        super(BiDict, self).__delitem__(key)    

class VariableTranslator(Singleton):
    def __init__(self, unittest_flag=False, verbose=0):
        if unittest_flag:
            # value not used, when we're testing will mock out call to read_yaml
            # below with actual translation table to use for test
            config_files = ['dummy_filename']
        else:
            paths = PathManager()
            glob_pattern = os.path.join(paths.CODE_ROOT, 'src', 'config_*.yml')
            config_files = glob.glob(glob_pattern)

        # always have CF-compliant option, which does no translation
        self.field_dict = {'CF':{}} 
        for filename in config_files:
            file_contents = read_yaml(filename)

            if type(file_contents['convention_name']) is str:
                file_contents['convention_name'] = [file_contents['convention_name']]
            for conv in file_contents['convention_name']:
                if verbose > 0: print 'XXX found ' + conv
                self.field_dict[conv] = BiDict(file_contents['var_names'])

    def toCF(self, convention, varname_in):
        if convention == 'CF': 
            return varname_in
        assert convention in self.field_dict, \
            "Variable name translation doesn't recognize {}.".format(convention)
        temp = self.field_dict[convention].inverse[varname_in]
        if len(temp) == 1:
            return temp[0]
        else:
            return temp
    
    def fromCF(self, convention, varname_in):
        if convention == 'CF': 
            return varname_in
        assert convention in self.field_dict, \
            "Variable name translation doesn't recognize {}.".format(convention)
        return self.field_dict[convention][varname_in]

# ------------------------------------

def read_yaml(file_path, verbose=0):
    """Wrapper to the ``safe_load`` function of the `PyYAML <https://pyyaml.org/>`_ 
    module. Wrapping file I/O simplifies unit testing.

    Args:
        file_path (:obj:`str`): path of the YAML file to read.
        verbose (:obj:`int`, optional): Logging verbosity level. Default 0.

    Returns:
        :obj:`dict` containing the parsed contents of the file.
    """
    assert os.path.exists(file_path), \
        "Couldn't find file {}.".format(file_path)
    try:    
        with open(file_path, 'r') as file_obj:
            file_contents = yaml.safe_load(file_obj)
    except IOError:
        print 'Fatal IOError when trying to read {}. Exiting.'.format(file_path)
        exit()

    if (verbose > 2):
        print yaml.dump(file_contents)  #print it to stdout 
    return file_contents

def write_yaml(struct, file_path, verbose=0):
    """Wrapper to the ``dump`` function of the `PyYAML <https://pyyaml.org/>`_ 
    module. Wrapping file I/O simplifies unit testing.

    Args:
        struct (:obj:`dict`)
        file_path (:obj:`str`): path of the YAML file to write.
        verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
    """
    try:
        with open(file_path, 'w') as file_obj:
            yaml.dump(struct, file_obj)
    except IOError:
        print 'Fatal IOError when trying to write {}. Exiting.'.format(file_path)
        exit()

def get_available_programs(verbose=0):
    return {'py': 'python', 'ncl': 'ncl', 'R': 'Rscript'}
    #return {'py': sys.executable, 'ncl': 'ncl'}  

def makefilepath(varname,timefreq,casename,datadir):
    """ 
    USAGE (varname, timefreq, casename, datadir )
        str varname  (as set by src/config_*.yml.py)
        str timefreq "mon","day","6hr","3hr","1hr"
        str datadir directory where model data lives

    """
    return datadir+"/"+timefreq+"/"+casename+"."+varname+"."+timefreq+".nc"

def setenv(varname,varvalue,env_dict,verbose=0,overwrite=True):
    """Wrapper to set environment variables.

    Args:
        varname (:obj:`str`): Variable name to define
        varvalue: Value to assign. Coerced to type :obj:`str` before being set.
        env_dict (:obj:`dict`): Copy of 
        verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
        overwrite (:obj:`bool`): If set to `False`, do not overwrite the values
            of previously-set variables. 
    """
    if (not overwrite) and (varname in env_dict): 
        if (verbose > 0): print "Not overwriting ENV ",varname," = ",env_dict[varname]
    else:
        if ('varname' in env_dict) and (env_dict[varname] != varvalue) and (verbose > 0): 
            print "WARNING: setenv ",varname," = ",varvalue," overriding previous setting ",env_dict[varname]
        env_dict[varname] = varvalue

        # environment variables must be strings
        if type(varvalue) is bool:
            if varvalue == True:
                varvalue = '1'
            else:
                varvalue = '0'
        elif type(varvalue) is not str:
            varvalue = str(varvalue)
        os.environ[varname] = varvalue

        if (verbose > 0): print "ENV ",varname," = ",env_dict[varname]
    if ( verbose > 2) : print "Check ",varname," ",env_dict[varname]

def check_required_envvar(*varlist):
    verbose=0
    varlist = varlist[0]   #unpack tuple
    for n in range(len(varlist)):
        if ( verbose > 2): print "checking envvar ",n,varlist[n],str(varlist[n])
        try:
            test = os.environ[varlist[n]]
        except:
            print "ERROR: Required environment variable ",varlist[n]," not found "
            print "       Please set in input file (default namelist) as VAR ",varlist[n]," value "
            exit()


def check_required_dirs(already_exist =[], create_if_nec = [], verbose=3):
    # arguments can be envvar name or just the paths
    filestr = __file__+":check_required_dirs: "
    errstr = "ERROR "+filestr
    if verbose > 1: filestr +" starting"
    for dir_in in already_exist + create_if_nec : 
        if verbose > 1: "\t looking at "+dir_in
 
        if dir_in in os.environ:  
            dir = os.environ[dir_in]
        else:
            if verbose>2: print(" envvar "+dir_in+" not defined")    
            dir = dir_in

        if not os.path.exists(dir):
            if not dir_in in create_if_nec:
                if (verbose>0): 
                    print errstr+dir_in+" = "+dir+" directory does not exist"
                    #print "         and not create_if_nec list: "+create_if_nec
                exit()
            else:
                print(dir_in+" = "+dir+" created")
                os.makedirs(dir)
        else:
            print("Found "+dir)

def parse_mdtf_args(args, config, rel_paths_root='', verbose=0):
    # overwrite default args in config file with command-line options.
    if args is not None:
        for section in ['paths', 'settings']:
            for key in config[section]:
                if (key in args.__dict__) and (args.__getattribute__(key) != None):
                    config[section][key] = args.__getattribute__(key)
        if 'CODE_ROOT' in args.__dict__ and (args.CODE_ROOT != None):
            # only let this be overridden if we're in a unit test
            rel_paths_root = args.CODE_ROOT

    cwd = os.getcwd()
    if rel_paths_root != '':
        os.chdir(rel_paths_root)
    for key, val in config['paths'].items():
        # convert relative to absolute paths
        config['paths'][key] = os.path.realpath(val)
    os.chdir(cwd)

    paths = PathManager(config['paths']) # initialize
    check_required_dirs(
        already_exist = [paths.CODE_ROOT, paths.MODEL_DATA_ROOT, paths.OBS_DATA_ROOT], 
        create_if_nec = [paths.WORKING_DIR, paths.OUTPUT_DIR], 
        verbose=verbose
        )
    return config

def set_mdtf_env_vars(config, verbose=0):
    config['envvars'] = {}
    for key, val in config['paths'].items():
        setenv(key, val, config['envvars'], verbose=verbose)
    for key, val in config['settings'].items():
        setenv(key, val, config['envvars'], verbose=verbose)

    # following are redundant but used by PODs
    paths = PathManager()
    setenv("RGB",paths.CODE_ROOT+"/src/rgb",config['envvars'], verbose=verbose)
