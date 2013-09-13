#!/usr/bin/env python

# Built-in
import glob
import math
import os
import shutil
import sys
import time
import webbrowser

# ReelFX
from app_manager.hou_executer import HouExecuter, MantraExecuter
from app_manager.session_manager import SessionManager
from farm_lib.farm_enums import JobType, QubeLanguage, FrameDistribution
from farm_lib.farm_utils import QubeTrigger, QubeEventName, QubeAgenda
from farm_lib.qube_job import QubeJob
from farm_lib.qube_submitter import QubeSubmitter
import path_lib
from pipe_api.scene_archive import scene_archive
from pipe_core.model.wip_output import WipOutputManager, WipOutput
from pipe_core.model.wip_output_types import WipOutputType
from pipe_utils.application import Application
from pipe_utils.email_utils import get_email_address
from pipe_utils.sequence import FrameSet
from pipe_utils.string_utils import obj_to_str
from pipe_utils.system_utils import get_user
from pipe_utils.version_utils import VersionManager
from pipe_utils import xml_utils

#------------------------------------------------------------------------------
# GLOBALS
#------------------------------------------------------------------------------

#------------------------------------------------------------------------------
# CLASSES
#------------------------------------------------------------------------------
class Dispatcher(object):
    def __init__(self, wip_ctx, path_ctx, resolution, outformat,
                 layer_info, after_job = None, test_only=False, notes='',
                 priority=1000, cpus=1):
        self.user = get_user()
        self.email_address = get_email_address(self.user)
        self.wip_ctx = wip_ctx
        # Retrieve the path formulas based on wip ctx
        self.get_path_formulas()
        self.path_ctx = path_ctx
        self.resolution = resolution
        self.outformat = outformat
        self.layer_info = layer_info
        self.stringify_elements()
        self.notes = notes
        self.priority = priority
        self.cpus = cpus
        self.scene_path = self.wip_ctx.get_default_scene_path()
        # The scene archive path may be an assembly
        self.scene_archive_path = scene_archive(
            self.scene_path,
            path_formula=self.archive_formula,
        )
        self.scene_archive_basename = os.path.splitext(
            os.path.basename(self.scene_archive_path)
        )[0]
        self.hou_frame_pattern = '$F4'
        self.wip_output_mgr = WipOutputManager.instance(pipe_ctx=self.wip_ctx)
        self.output_versions = self.get_output_versions()
        self.after_job = after_job
        self.submission_path = self.path_ctx.get_path(
            self.submission_formula,
            disc=self.wip_ctx.discipline.short_name
        )
        self.xml_path = os.path.join(
            self.submission_path,
            '{0}.xml'.format(self.scene_archive_basename)
        )
        self.py_script = path_lib.join(
            os.environ['PKG_LIGHTNING'],
            'rhou',
            'create_renders.py'
        )
        self.test_only = test_only

    def __repr__(self):
        return '%s %s_%s_%s' % (self.__class__, self.wip_ctx.sequence,
                                  self.wip_ctx.shot, self.wip_ctx.wip)

    def add_email_callback(self, qube_job):
        """ Add a callback call to the qube job for emails on
        fail-complete-kill.
        """
        # Add email callback
        lang = QubeLanguage.get_enum('mail')
        code = ''
        qube_job.add_callback(code, QubeTrigger.get_fail_self_trigger(), language=lang)
        qube_job.add_callback(code, QubeTrigger.get_complete_self_trigger(), language=lang)
        # qube_job.add_callback(code, QubeTrigger.get_kill_self_trigger(), language=lang)
        return qube_job

    def add_live_link_callback(self, qube_job, source, link):
        raise NotImplementedError
        """ Add a callback call to create a live link upon completion."""
        code = (
            "import os;"
            "os.symlink({0}, {1});"
        ).format(source, link)
        qube_job.add_callback(code, QubeTrigger.get_complete_self_trigger())
        return qube_job

    def create_xml(self):
        root = xml_utils.ElementTree.Element('submission')
        root.set('version', '1')
        root.set('date', '1')
        # List of sub elements under root
        sub_names = ['shot', 'resolution', 'output', 'scenepath', 'rlcfile',
                     'shotopts', 'renders']
        sub_elements = self.create_sub_elements(root, sub_names)
        self.populate_image_info(sub_elements)
        self.populate_layer_info(sub_elements['renders'])
        return root

    def create_sub_elements(self, root, elements):
        """ Create the base sub elements beneath the root node. """
        nodes = {}
        for element in elements:
            nodes[element] = xml_utils.ElementTree.SubElement(root, element)
        return nodes

    def get_path_formulas(self):
        if self.wip_ctx.is_assembly():
            self.archive_formula = 'am_wip_backup_version_dir'
            self.submission_formula = 'am_render_dispatcher_dir'
        elif self.wip_ctx.is_shot():
            self.archive_formula = 'sh_wip_backup_version_dir'
            self.submission_formula = 'sh_render_dispatcher_dir'
        else:
            raise AttributeError( "Currently unknown path formulas for dispatcher")

    def write_xml(self, root, path):
        """ Write the xml out to a file. """
        xml_utils.indent(root)
        tree = xml_utils.ElementTree.ElementTree(root)
        if not os.path.exists(self.submission_path):
            os.makedirs(self.submission_path)
        tree.write(path)

    def submit_jobs(self):
        """ Created a secondary function that will do both
        create_qube_jobs and create_dependent_jobs as well
        as submit.  This is because there is a possible
        bug when attempting to pass around a QubeSubmitter.
        """
        # Create base qube submitter
        submitter = self.create_qube_jobs()
        submitter.submit()
        job_ids = submitter.get_job_ids()
        return job_ids

    def create_qube_jobs(self):
        """(farm_lib.qube_submitter.QubeSubmitter)
        *Currently deprecated.  Use submit_jobs instead* Create the qube jobs
        for the render passes.  The first job that is created is the Houdini job
        which will create the mantra nodes for each pass, apply all the
        settings, and create the IFDs.  Each Mantra pass job is created as an
        after job that will call the Mantra executer and render the IFDs.

        """
        # Create base qube submitter
        submitter = QubeSubmitter()
        mgr = SessionManager.inst()
        env = mgr.env_manager
        app_versions = env.get_app_versions_dict()
        hou_version = app_versions[Application.HOU]
        kwargs = {}
        # Requirements that need to be determined
        # requirements
        kwargs['priority'] = self.priority
        kwargs['cpus'] = self.cpus
        kwargs['allow_local'] = False
        kwargs['requirements'] = ['host.dead_hbatch=1']
        executer = HouExecuter(
            self.wip_ctx,
            app_versions,
            py_args = self.render_args,
            startup_scene = self.scene_archive_path,
        )
        executer.batch_mode = True
        executer.py_script = self.py_script
        cluster = 'dead_hbatch'
        qube_job = QubeJob(
            executer,
            JobType.PROCESS,
            cluster,
            mailaddress=self.email_address,
            label='IFD_Creation_{seq}_{shot}'.format(seq=self.wip_ctx.sequence,
                                                     shot=self.wip_ctx.shot),
            **kwargs
        )
        if self.after_job:
            qube_job.add_dependency(self.after_job, QubeEventName.COMPLETE)

        qube_job = self.add_email_callback(qube_job)
        submitter.append(qube_job)
        # Add all the IFD dependent jobs
        # self.create_dependent_jobs(submitter, app_versions)
        return submitter

    def create_dependent_jobs(self, submitter, app_versions):
        """ Create the dependent MantraExecuter job that will render the IFDs
        when they are created.

        """
        mantra_jobs = []
        for i, layer in enumerate(self.layer_info):
            frame_range = FrameSet.parse(layer['frame_range'])
            executer = MantraExecuter(self.wip_ctx, self.ifd_paths[i], app_versions)
            job_settings = self.generate_layer_settings(layer)
            cluster = 'dead'
            job = QubeJob(
                executer,
                JobType.RENDER,
                cluster,
                label='Render_{0}'.format(layer['layer']),
                mailaddress=self.email_address,
                **job_settings
            )
            job.add_dependency(submitter[0], QubeEventName.COMPLETE)
            job = self.add_email_callback(job)
            # Allow user to change the distribution
            job.agendas = QubeAgenda.gen_frame_set_tasks([frame_range], FrameDistribution.SINGLE)
            submitter.append(job)

    def generate_layer_settings(self, layer):
        """(dict) Generate a dictionary to set the qube jobs for layer
        jobs.

        """
        settings = {}
        settings['cpus'] = layer['cpus']
        settings['priority'] = layer['priority']
        settings['allow_local'] = False
        settings['requirements'] = ['host.dead=1']
        return settings

    def get_default_camera(self):
        """(str) Retrieve the default camera from the shot"""
        shot_obj = self.wip_ctx.get_shot_obj()
        for cam_inst in shot_obj.camera_instances:
            if not cam_inst.active:
                continue
            if cam_inst.is_main:
                return cam_inst.name
        return ''

    def populate_image_info(self, sub_elements):
        """ Populate the image information like shot, sequence, format,
        and resolution.
        """
        sub_elements['shot'].set('sequence', str(self.wip_ctx.sequence))
        sub_elements['shot'].set('shot', str(self.wip_ctx.shot))
        sub_elements['resolution'].set('width', str(self.resolution.width))
        sub_elements['resolution'].set('height', str(self.resolution.height))
        sub_elements['resolution'].set('aspect', str(self.resolution.aspect))
        sub_elements['output'].set('format', self.outformat)

    def populate_layer_info(self, renders):
        """ Populate each layer information. """
        for layer in self.layer_info:
            render = xml_utils.ElementTree.SubElement(renders, 'render')
            render.set('layer', layer['layer'])
            render.set('right', layer['renderRightEye'])
            render.set('left', layer['renderLeftEye'])
            render.set('proc', layer['cpus'])
            render.set('priority', layer['priority'])
            render.set('range', layer['frame_range'])
            render.set('up', layer['up'])
            render.set('camera', layer['camera'])

    def stringify_elements(self):
        """ Xml doesn't like things not string.  Stringify them. """
        for layer in self.layer_info:
            for key, attr in layer.iteritems():
                layer[key] = str(attr)

    def submit(self):
        """ (dict) Create the xml and submit all the jobs. """
        root = self.create_xml()
        self.write_xml(root, self.xml_path)

        if self.test_only:
            with open('/people/slu/renderArgs.txt', 'w') as myFile:
                myFile.write(obj_to_str(self.render_args, useb64encode=True))
        else:
            job_ids = self.submit_jobs()
        return job_ids

    @property
    def base_render_path(self):
        """Returns the base path for the renders"""
        return self.wip_outputs[0].get_output_base_dirs()[1]

    @property
    def base_ifd_path(self):
        """Returns the base path for the IFDs"""
        return self.wip_outputs[0].get_output_base_dirs()[0]

    @property
    def render_base_dir(self):
        """ Returns the base directory path for a render folder. """
        return [wip_output.get_output_base_dirs()[1] for wip_output in self.wip_outputs]

    @property
    def render_paths(self):
        """Returns a list of render paths for each pass. """
        render_paths = []
        for version in self.output_versions:
            render_paths.append(version.get_path())
        return render_paths

    @property
    def ifd_paths(self):
        """Returns a list of IFD paths for each pass. """
        ifd_paths = []
        for version in self.output_versions:
            ifd_paths.append(version.get_path(WipOutputType.MANTRA_IFD))
        return ifd_paths

    @property
    def render_args(self):
        """ Return all the arguments to pass to the houdini script. """
        return {
            'xml_path' : self.xml_path,
            'path_ctx' : self.path_ctx,
            'image_paths' : self.render_paths,
            'ifd_paths' : self.ifd_paths,
            'render_scene' : self.scene_archive_path,
            'layer_info' : self.layer_info
        }

    @property
    def wip_outputs(self):
        wip_outputs = []
        for layer in self.layer_info:
            wip_output = self.wip_output_mgr.get_wip_output(layer['layer'])
            wip_outputs.append(wip_output)
        return wip_outputs

    def get_output_versions(self):
        """ Returns the list of WipOutputVersion for every pass. """
        versions = []
        for i, wip_output in enumerate(self.wip_outputs):
            version = wip_output.get_latest_version()
            # If there is no version, create one.  If the
            # version up flag is set, version up the wipoutput
            if not version:
                version = wip_output.get_version(1)
            else:
                if eval(self.layer_info[i]['up']):
                    current_ver = int(version.number)
                    version = wip_output.get_version(current_ver + 1)
            version.note = self.notes
            version.save()
            versions.append(version)
        return versions

