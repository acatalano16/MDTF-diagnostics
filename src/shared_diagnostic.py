import os
import sys
import glob
import shutil
import util
from util import setenv # TODO: fix

class Diagnostic(object):
    """Class holding configuration for a diagnostic script.

    This is the analogue of TestCase in the xUnit analogy.

    Object attributes are read from entries in the settings section of the POD's
    settings.yml file upon initialization.

    Attributes:
        driver (:obj:`str`): Filename of the top-level driver script for the POD.
        long_name (:obj:`str`): POD's name used for display purposes. May contain spaces.
        description (:obj:`str`): Short description of POD inserted by the link in the
            top-level index.html file.
        required_programs (:obj:`list` of :obj:`str`, optional): List of 
            executables required by the POD (typically language interpreters). 
            validate_environment.sh will make sure these are on the environment's
            $PATH before the POD is run.
        required_ncl_scripts (:obj:`list` of :obj:`str`, optional): List of NCL 
            scripts required by the POD, if any.  
            validate_environment.sh will make sure these are on the environment's
            $PATH before the POD is run.
    """

    def __init__(self, pod_name, verbose=0):
        """POD initializer. Given a POD name, we attempt to read a settings.yml 
        file in a subdirectory of ``/diagnostics`` by that name and parse the
        contents.

        Args:
            pod_name (:obj:`str`): Name of the POD to initialize.
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
        """
        paths = util.PathManager()

        self.name = pod_name
        self.__dict__.update(paths.podPaths(self))
        file_contents = util.read_yaml(
            os.path.join(self.POD_CODE_DIR, 'settings.yml'))

        config = self._parse_pod_settings(file_contents['settings'], verbose)
        self.__dict__.update(config)
        config = self._parse_pod_varlist(file_contents['varlist'], verbose)
        self.varlist = config

    def _parse_pod_settings(self, settings, verbose=0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.__init__`.

        Args:
            settings (:obj:`dict`): Contents of the settings portion of the POD's
                settings.yml file.
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.

        Returns:
            Dict of parsed settings.
        """
        d = {}
        d['pod_name'] = self.name # redundant
        # define empty defaults to avoid having to test existence of attrs
        for str_attr in ['program', 'driver', 'long_name', 'description', 
            'env', 'convention']:
            d[str_attr] = ''
        for list_attr in ['varlist', 'found_files', 'missing_files',
            'required_programs', 'required_python_modules', 
            'required_ncl_scripts', 'required_r_packages']:
            d[list_attr] = []
        for dict_attr in ['pod_env_vars']:
            d[dict_attr] = {}
        for obj_attr in ['process_obj', 'logfile_obj']:
            d[obj_attr] = None

        # overwrite with contents of settings.yaml file
        d.update(settings)

        if 'variable_convention' in d:
            d['convention'] = d['variable_convention']
            del d['variable_convention']
        elif d['convention'] == '':
            d['convention'] = 'CF'
        for list_attr in ['required_programs', 'required_python_modules', 
            'required_ncl_scripts', 'required_r_packages']:
            if type(d[list_attr]) != list:
                d[list_attr] = [d[list_attr]]
        if (verbose > 0): 
            print self.name + " settings: "
            print d
        return d

    def _parse_pod_varlist(self, varlist, verbose=0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.__init__`.

        Args:
            varlist (:obj:`list` of :obj:`dict`): Contents of the varlist portion 
                of the POD's settings.yml file.
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.

        Returns:
            varlist
        """
        default_file_required = False 
        for idx, var in enumerate(varlist):
            assert var['freq'] in ['1hr', '3hr', '6hr', 'day', 'mon'], \
                "WARNING: didn't find "+var['freq']+" in frequency options "+\
                    " (set in "+__file__+": parse_pod_varlist)"
            if 'requirement' in var:
                varlist[idx]['required'] = (var['requirement'].lower() == 'required')
            else:
                varlist[idx]['required'] = default_file_required
            if ('alternates' not in var):
                varlist[idx]['alternates'] = []
            elif ('alternates' in var) and (type(var['alternates']) is not list):
                varlist[idx]['alternates'] = [var['alternates']]
        if (verbose > 0): 
            print self.name + " varlist: "
            print varlist
        return varlist

    # -------------------------------------

    def setUp(self, verbose=0):
        """Perform filesystem operations and checks prior to running the POD. 

        In order, this 1) sets environment variables specific to the POD, 2)
        creates POD-specific working directories, and 3) checks for the existence
        of the POD's driver script and requested data files.

        Note:
            The existence of data files is checked here, with 
            :meth:`~shared_diagnostic.Diagnostic._check_for_varlist_files`,
            but the runtime environment is validated separately as a function of
            :meth:`environment_manager.EnvironmentManager.run`. This is because 
            each POD is run in a subprocess (due to the necessity of supporting
            multiple languages) so the validation must take place in that 
            subprocess.
        """
        self._set_pod_env_vars(verbose)
        self._setup_pod_directories()

        self._check_pod_driver(verbose)
        var_files = self._check_for_varlist_files(self.varlist, verbose)
        self.found_files = var_files['found_files']
        self.missing_files = var_files['missing_files']
        if self.missing_files != []:
            print "WARNING: POD ",self.name," missing required input files:"
            print self.missing_files
        else:
            if (verbose > 0): print "No known missing required input files"

    def _set_pod_env_vars(self, verbose=0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.setUp`.

        Args:
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.

        Returns:
            Dict of POD-specific environment variables that were set.
        """
        pod_envvars = {}
        # location of POD's code
        setenv("POD_HOME", self.POD_CODE_DIR, pod_envvars, verbose=verbose)
        # POD's observational data
        setenv("OBS_DATA", self.POD_OBS_DATA, pod_envvars, verbose=verbose)
        # POD's subdir within working directory
        setenv("WK_DIR", self.POD_WK_DIR, pod_envvars, verbose=verbose)

        # optional POD-specific env vars defined in settings.yml
        for key, val in self.pod_env_vars.items():
            setenv(key, val, pod_envvars, verbose=verbose) 
        return pod_envvars

    def _setup_pod_directories(self, verbose =0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.setUp`.

        Args:
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
        """
        util.check_required_dirs(
            already_exist =[self.POD_CODE_DIR, self.POD_OBS_DATA], 
            create_if_nec = [self.POD_WK_DIR], 
            verbose=verbose)
        dirs = ['', 'model', 'model/PS', 'model/netCDF', 'obs', 'obs/PS','obs/netCDF']
        for d in dirs:
            if not os.path.exists(os.path.join(self.POD_WK_DIR, d)):
                os.makedirs(os.path.join(self.POD_WK_DIR, d))

    def _check_pod_driver(self, verbose=0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.setUp`.

        Args:
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
        """
        func_name = "check_pod_driver "
        if (verbose > 1):  print func_name," received POD settings: ", self.__dict__
        programs = util.get_available_programs()

        if self.driver == '':  
            print "WARNING: no valid driver entry found for ", self.name
            #try to find one anyway
            try_filenames = [self.name+".", "driver."]      
            file_combos = [ file_root + ext for file_root in try_filenames for ext in programs.keys()]
            if verbose > 1: 
                print "Checking for possible driver names in ",self.POD_CODE_DIR," ",file_combos
            for try_file in file_combos:
                try_path = os.path.join(self.POD_CODE_DIR, try_file)
                if verbose > 1: print " looking for driver file "+try_path
                if os.path.exists(try_path):
                    self.driver = try_path
                    if (verbose > 0): print "Found driver script for "+self.name+" : "+ self.driver
                    break    #go with the first one found
                else:
                    if (verbose > 1 ): print "\t "+try_path+" not found..."
        errstr_nodriver = "No driver script found for package "+self.name +"\n\t"\
            +"Looked in "+self.POD_CODE_DIR+" for pod_name.* or driver.* \n\t"\
            +"To specify otherwise, add a line to "+self.name+"/settings file containing:  driver driver_script_name \n\t" \
            +"\n\t"+func_name
        assert (self.driver != ''), errstr_nodriver

        if not os.path.isabs(self.driver): # expand relative path
            self.driver = os.path.join(self.POD_CODE_DIR, self.driver)
        errstr = "ERROR: "+func_name+" can't find "+ self.driver+" to run "+self.name
        assert os.path.exists(self.driver), errstr 

        if self.program == '':
            # Find ending of filename to determine the program that should be used
            driver_ext  = self.driver.split('.')[-1]
            # Possible error: Driver file type unrecognized
            errstr_badext = func_name+" does not know how to call a ."+driver_ext+" file \n\t"\
                +"Available programs: "+str(programs.keys())
            assert (driver_ext in programs), errstr_badext
            self.program = programs[driver_ext]
            if ( verbose > 1): print func_name +": Found program "+programs[driver_ext]
        errstr = "ERROR: "+func_name+" can't find "+ self.program+" to run "+self.name    

    def _check_for_varlist_files(self, varlist, verbose=0):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.setUp`.

        Args:
            varlist (:obj:`list` of :obj:`dict`): Contents of the varlist portion 
                of the POD's settings.yml file.
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.

        Returns:
            Dict with two entries, ``found_files`` and ``missing_files``, containing
                lists of paths to found and missing data files, respectively.
        """
        translate = util.VariableTranslator()
        func_name = "\t \t check_for_varlist_files :"
        if ( verbose > 2 ): print func_name+" check_for_varlist_files called with ", varlist
        found_list = []
        missing_list = []
        for item in varlist:
            if (verbose > 2 ): print func_name +" "+item
            filepath = util.makefilepath(item['name_in_model'],item['freq'],os.environ['CASENAME'],os.environ['DATADIR'])

            if (os.path.isfile(filepath)):
                print "found ",filepath
                found_list.append(filepath)
                continue
            if (not item['required']):
                print "WARNING: optional file not found ",filepath
                continue
            if not (('alternates' in item) and (len(item['alternates'])>0)):
                print "ERROR: missing required file ",filepath,". No alternatives found"
                missing_list.append(filepath)
            else:
                alt_list = item['alternates']
                print "WARNING: required file not found ",filepath,"\n \t Looking for alternatives: ",alt_list
                for alt_item in alt_list: # maybe some way to do this w/o loop since check_ takes a list
                    if (verbose > 1): print "\t \t examining alternative ",alt_item
                    new_var = item.copy()  # modifyable dict with all settings from original
                    new_var['name_in_model'] = alt_item # translation done in DataManager._setup_pod()
                    del new_var['alternates']    # remove alternatives (could use this to implement multiple options)
                    if ( verbose > 2): print "created new_var for input to check_for_varlist_files",new_var
                    new_files = self._check_for_varlist_files([new_var],verbose=verbose)
                    found_list.extend(new_files['found_files'])
                    missing_list.extend(new_files['missing_files'])

        if (verbose > 2): print "check_for_varlist_files returning ",missing_list
        # remove empty list entries
        files = {}
        files['found_files'] = [x for x in found_list if x]
        files['missing_files'] = [x for x in missing_list if x]
        return files

    # -------------------------------------

    def run_command(self):
        """Produces the shell command to run the POD. Called by 
        :meth:`environment_manager.EnvironmentManager.run`.

        Returns:
            (:obj:`str`) Command-line invocation to run the POD.
        """
        return self.program + ' ' + self.driver
    
    def validate_command(self):
        """Produces the shell command to validate the POD's runtime environment 
        (ie, check for all requested third-party module dependencies.)

        Called by :meth:`environment_manager.EnvironmentManager.run`. 
        Dependencies are passed as arguments to the shell script 
        ``src/validate_environment.sh``, which is invoked in the POD's subprocess
        before the POD is run.

        Returns:
            (:obj:`str`) Command-line invocation to validate the POD's runtime environment.
        """
        paths = util.PathManager()
        command_path = os.path.join(paths.CODE_ROOT, 'src', 'validate_environment.sh')
        command = [
            command_path,
            ' -v',
            ' -p '.join([''] + self.required_programs),
            ' -z '.join([''] + self.pod_env_vars.keys()),
            ' -a '.join([''] + self.required_python_modules),
            ' -b '.join([''] + self.required_ncl_scripts),
            ' -c '.join([''] + self.required_r_packages)
        ]
        return ''.join(command)

    # -------------------------------------

    def tearDown(self, verbose=0):
        """Performs cleanup tasks when the POD has finished running.

        In order, this 1) creates the POD's HTML output page from its included
        template, replacing ``CASENAME`` and other template variables with their
        current values, and adds a link to the POD's page from the top-level HTML
        report; 2) converts the POD's output plots (in PS or EPS vector format) 
        to a bitmap format for webpage display; 3) Copies all requested files to
        the output directory and deletes temporary files.

        Args:
            verbose (:obj:`int`, optional): Logging verbosity level. Default 0.
        """
        # shouldn't need to re-set env vars, but used by 
        # convective_transition_diag to set filename info 
        self._set_pod_env_vars(verbose=verbose)

        self._make_pod_html()
        self._convert_pod_figures()
        self._cleanup_pod_files()

        if verbose > 0: 
            print("---  MDTF.py Finished POD "+self.name+"\n")
            # elapsed = timeit.default_timer() - start_time
            # print(pod+" Elapsed time ",elapsed)

    def _make_pod_html(self):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.tearDown`.  
        """
        html_file = os.path.join(self.POD_WK_DIR, self.name+'.html')
        temp_file = os.path.join(self.POD_WK_DIR, 'tmp.html')

        if os.path.exists(html_file):
            os.remove(html_file)
        shutil.copy2(os.path.join(self.POD_CODE_DIR, self.name+'.html'), self.POD_WK_DIR)
        os.system("cat "+ html_file \
            + " | sed -e s/casename/" + os.environ["CASENAME"] + "/g > " \
            + temp_file)
        # following two substitutions are specific to convective_transition_diag
        # need to find a more elegant way to handle this
        if self.name == 'convective_transition_diag':
            temp_file2 = os.path.join(self.POD_WK_DIR, 'tmp2.html')
            if ("BULK_TROPOSPHERIC_TEMPERATURE_MEASURE" in os.environ) \
                and os.environ["BULK_TROPOSPHERIC_TEMPERATURE_MEASURE"] == "2":
                os.system("cat " + temp_file \
                    + " | sed -e s/_tave\./_qsat_int\./g > " + temp_file2)
                shutil.move(temp_file2, temp_file)
            if ("RES" in os.environ) and os.environ["RES"] != "1.00":
                os.system("cat " + temp_file \
                    + " | sed -e s/_res\=1\.00_/_res\=" + os.environ["RES"] + "_/g > " \
                    + temp_file2)
                shutil.move(temp_file2, temp_file)
        shutil.copy2(temp_file, html_file) 
        os.remove(temp_file)

        # add link and description to main html page
        html_file = os.path.join(self.MODEL_WK_DIR, 'index.html')
        a = os.system("cat " + html_file + " | grep " + self.name)
        if a != 0:
            os.system("echo '<H3><font color=navy>" + self.description \
                + " <A HREF=\""+ self.name+"/"+self.name+".html\">plots</A></H3>' >> " \
                + html_file)

    def _convert_pod_figures(self):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.tearDown`.
        """
        dirs = ['model/PS', 'obs/PS']
        exts = ['ps', 'eps']
        files = []
        for d in dirs:
            for ext in exts:
                pattern = os.path.join(self.POD_WK_DIR, d, '*.'+ext)
                files.extend(glob.glob(pattern))
        for f in files:
            (dd, ff) = os.path.split(os.path.splitext(f)[0])
            ff = os.path.join(os.path.dirname(dd), ff) # parent directory/filename
            command_str = 'convert '+ os.environ['convert_flags'] + ' ' \
                + f + ' ' + ff + '.' + os.environ['convert_output_fmt']
            os.system(command_str)

    def _cleanup_pod_files(self):
        """Private method called by :meth:`~shared_diagnostic.Diagnostic.tearDown`.
        """
        # copy PDF documentation (if any) to output
        files = glob.glob(os.path.join(self.POD_CODE_DIR, '*.pdf'))
        for file in files:
            shutil.copy2(file, self.POD_WK_DIR)

        # copy premade figures (if any) to output 
        exts = ['gif', 'png', 'jpg', 'jpeg']
        globs = [os.path.join(self.POD_OBS_DATA, '*.'+ext) for ext in exts]
        files = []
        for pattern in globs:
            files.extend(glob.glob(pattern))
        for file in files:
            shutil.copy2(file, os.path.join(self.POD_WK_DIR, 'obs'))

        # remove .eps files if requested
        if os.environ["save_ps"] == "0":
            dirs = ['model/PS', 'obs/PS']
            for d in dirs:
                if os.path.exists(os.path.join(self.POD_WK_DIR, d)):
                    shutil.rmtree(os.path.join(self.POD_WK_DIR, d))

        # delete netCDF files if requested
        if os.environ["save_nc"] == "0":    
            dirs = ['model/netCDF', 'obs/netCDF']
            for d in dirs:
                if os.path.exists(os.path.join(self.POD_WK_DIR, d)):
                    shutil.rmtree(os.path.join(self.POD_WK_DIR, d))