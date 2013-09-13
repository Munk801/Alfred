

#----------------------------------------------------------------------------#
#------------------------------------------------------------ HEADER_START --#
"""
@newField description: Description
@newField revisions: Revisions
@newField departments: Departments
@newField applications: Applications

@author:
    slu

@version:
    0.0.22

@organization:
    Reel FX Creative Studios

@description:
    RST Dispatcher

@departments:
    - comp
    - lighting

@applications:
    - general

@revisions:

"""
#----------------------------------------------------------------------------#
#-------------------------------------------------------------- HEADER_END --#

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#
# Built-in
import glob
import math
import os
import shutil
import sys
import time
import webbrowser

import itertools, operator
import OpenEXR
from xml.etree import cElementTree
import cPickle
# Third party
from PyQt4 import QtGui
from PyQt4 import QtCore

# ReelFX
from app_manager.hou_executer import HouExecuter, MantraExecuter
from farm_lib.qube_job import QubeJob
from houdini_tools import hda_manager
from houdini_tools.ui.camera_update_view import OutdatedCameraView
import lightning
from lightning.dispatcher import Dispatcher as CmdDispatcher
from lightning.ui import file_browsers
from ui_lib.inputs.pipe_context_input import RPipeContextInput
from ui_lib.layouts.box_layout import RHBoxLayout, RVBoxLayout
from ui_lib.views.wip_browser import RWipBrowser
from ui_lib.window import RMainWindow, RDialog
import ui_lib_old
import ui_lib_old.widgets.common as widgets

from pipe_api.env import get_pipe_context
from pipe_core.pipe_context import PipeContext, WipContext
from path_lib import PathContext
from pipe_utils.preferences import save_preferences, load_preferences
from pipe_utils.resolution import Resolution
from pipe_utils.response import Response, Success
from pipe_utils.sequence import FrameRange
from pipe_utils import xml_utils
import qb

# This is temporary to figure out if we are in houdini
try:
    import hou
    from houdini_tools.hda_modules.rfxAbcCamera import rfxAbcCamera
    IN_HOU = True
except ImportError:
    IN_HOU = False
#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- CLASSES --#

class Dispatcher(ui_lib_old.BaseWidget):

    def __init__(self, *args, **kwargs):
        """
        __init__ is the constructor of the RSTDispatcher class.
        Initialize all of the forms and widgets of the main window
        Define class wide variables for widget access

        @param *args:
        @type *args:
        @param **kwargs:
        @type **kwargs:
        @returns: n/a (constructor method)

        """
        self.icondir = ui_lib_old.ui_utils.get_icon_directory()
        self._size = "/32x32/"

        # TO DO: REPLACE WITH PIPE_CONTEXT
        self.wip_ctx = get_pipe_context()

        self.show_longname = self.wip_ctx.project
        self.department = self.wip_ctx.discipline
        self.pipe_obj = self.wip_ctx.get_pipe_obj()
        self.shot_obj = self.wip_ctx.get_shot_obj()
        self.project_object = self.wip_ctx.get_project_obj()
        #self.context = path_extractor.extract(os.getcwd())

        self.root = kwargs.get('root')
        # PUT THIS BACK WHEN WE CAN GO TO HOU
        if not isinstance(self.root, lightning.groups.Root):
            self.root = lightning.root()

        self.inmaya = False
        defaults = {}
        defaults['title'] = 'Dispatcher'
        defaults['height'] = 900
        defaults['width'] = 1150
        defaults['init_app'] = True
        defaults.update(kwargs)
        ui_lib_old.BaseWidget.__init__(self, **defaults)
        self.setFont(QtGui.QFont("SansSerif", 8, QtGui.QFont.Bold))
        self.set_validations()
        self.actionhistory = []
        self.linkedrowlist = []
        self.passeslist = []
        self.tab2list = []
        self.default_frame_range = ""
        self.hero_frame = ""
        self.key_frames = ""
        self.globalstereobool = 0

        self.sheet = ""

        self.statusbar = QtGui.QStatusBar()
        self.mainlayout = QtGui.QVBoxLayout()
        self.setLayout(self.mainlayout)
        #self.toplayout = self._build_topform_layout()
        # Top form layout and connections
        self.toplayout = DispatcherTopformLayout(palette=self.palette())
        self.toplayout.connect(self.toplayout.scene_render_edit,
                     QtCore.SIGNAL('editingFinished ()'),
                     self._test_for_unlock)
        self.toplayout.connect(self.toplayout.scene_render_dialog_button,
                               QtCore.SIGNAL('clicked()'),
                               self.open_wip_browser)

        self._get_resolutions()
        self.menubar = QtGui.QMenuBar(self)
        self.menubar.setMinimumWidth(1500)
        self.menubar.setSizePolicy(QtGui.QSizePolicy.Ignored,
                                   QtGui.QSizePolicy.Ignored)

        # XXX TODO: Separate this into its own class
        #self.table = DispatcherTable(0, 13)
        self.table = QtGui.QTableWidget(0, 13)
        self.signalmapper = QtCore.QSignalMapper(self)
        self.connect(self.signalmapper,
                     QtCore.SIGNAL("mapped(const QString &)"),
                     self._modify_link_list)

        self.table.setHorizontalHeaderLabels(['Layer', 'Pass', 'Frame Range',
                                               'Link', '', 'L', 'R',
                                                'Up', 'Camera', 'Priority',
                                                 'Procs', 'Mantra Cluster', 'Hbatch Distribution'])

        self._build_bottom_tab()

        self.split = QtGui.QSplitter(QtCore.Qt.Vertical)

        self.mainlayout.addSpacing(18)
        self.mainlayout.addLayout(self.toplayout)
        self.mainlayout.addSpacing(10)
        self.split.addWidget(self.table)

        self._build_bottom_row()
        self.mainlayout.addWidget(self.split)
        self.split.addWidget(self.bottom_row_table)
        self.split.addWidget(self.bottomtab)

        self._build_bottom_buttons()
        self.mainlayout.addLayout(self.bottom_button_layout)

        self.mainlayout.addWidget(self.statusbar)

        self.pbar = QtGui.QProgressBar(self)
        self.pbar.setRange(0,100)

        self.mainlayout.addWidget(self.pbar)
        self.pbar.hide()

        self._lock_bottom_buttons()

        self._build_file_menu(self.menubar)
        self._build_help_menu(self.menubar)

        #ui_lib_old.ui_utils.set_style(self.menubar, fg='#999', bg='#222')
        #ui_lib_old.ui_utils.set_style(self, fg='#999', bg='#222')

        self.pal = self.palette()
        self.pal.setColor(QtGui.QPalette.Base, QtGui.QColor(155, 155, 155))
        self.pal.setColor(QtGui.QPalette.Window, QtGui.QColor(55, 55, 55))
        self.pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor("white"))
        self.pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("black"))
        self.pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(220,
                                                                 220, 220))
        self.pal.setColor(QtGui.QPalette.Button, QtGui.QColor("white"))

        self.setPalette(self.pal)
        self._firsttime = False
        if self.root:
            self._firsttime = True
            self.path_ctx = self.root.get_path_context()
            self._load_passes()
            name = self.path_ctx.get('name')
            pipe_ctx = PipeContext.from_path_context(self.path_ctx)
            label = '%s (%s)' % (name, pipe_ctx)
            self.toplayout.rst_edit.setText(label)
            #self._setup_scene_for_existing_root()
        #print self.style()

         #   self.setStyleSheet(sheet)
        #index = self.sequence_name.findText("9999")
        #self.sequence_name.setCurrentIndex(index)
        #index = self.shot_name.findText("0010")
        #self.shot_name.setCurrentIndex(index)
        #self._update_scene_and_rsf()

    def get_cameras(self, node, cameras):
        if rfxAbcCamera.is_rfx_abc_camera(node):
            return
        if node.type().name() == 'cam':
            cameras.append(node)
            return
        children = node.children()
        for child in children:
            self.get_cameras(child, cameras)
        return cameras

    def get_shot_default_camera(self):
        """(str) Retrieve the default camera from the shot"""
        pipe_obj = self.wip_ctx.get_pipe_obj()
        for cam_inst in pipe_obj.camera_instances:
            if not cam_inst.active:
                continue
            if cam_inst.is_main:
                return cam_inst.name
        return ''

    def populate_combo(self, combo_obj, field='mantra'):
        """Populate the combo with all the mantra clusters. """
        mapping = {
            'mantra' : ['dead', 'mantra', 'big_ram'],
            'hbatch' : ['dead_hbatch'],
            'hbatch_dist' : ['Single Frame', 'Frame Chunk'],
        }
        [combo_obj.addItem(sel) for sel in mapping[field]]

    # XXX TODO : This is temp.  Later we need to make a class
    def populate_cameras(self, camcombo, allow_specification=False):
        default_shot_cam = self.get_shot_default_camera()
        camcombo.addItem(default_shot_cam)
        # If we are in houdini, lets populate the cameras in scene.
        # Else, lets allow the user to input something.
        if IN_HOU:
            # Add all the cameras in the scene
            # XXX TODO: MOVE THE UI TO A DIFFERENT SPOT
            hou_node = hou.node('/')
            cameras = []
            # Get the cameras and rfxAbcCameras separately
            cameras = self.get_cameras(hou_node, cameras)
            rfxcameras = [camera for camera in rfxAbcCamera.find_all(hou_node)]
            cameras.extend(rfxcameras)
            camera_names = [c.name() for c in cameras]
            for cam in camera_names:
                camcombo.addItem(cam)
        elif not IN_HOU and allow_specification:
            camcombo.addItem("<specify cam>")
            camcombo.activated[str].connect(self.specify_camera)

    def specify_camera(self, text):
        """Open an input dialog to specify a camera"""
        if text == "<specify cam>":
            camera, ok = QtGui.QInputDialog.getText(self, 'Specify Camera',
                                                    'Specify a camera name:')
            if ok:
                table_row_count = self.table.rowCount()
                model = self.table.model()
                # THIS IS SO HARDCODEY! 8 is the camera column
                for row in range(0,table_row_count):
                    self.table.indexWidget(model.index(row, 8)).addItem(camera)

    def update_open_btn_state(self, *args, **kwargs):
        """
        Updates the enable state of the scene open button.
        """
        if not self._supports_wips:
            return
        state = bool(self.app_session and self.app_session.is_booted_up())
        if state and not self.wip_browser.valid_scene_selected():
            state = False
        self.open_btn.setEnabled(state)

    def on_wip_tree_double_clicked(self, wip_tree_item):
        """
        Callback when the user double clicks in the wip browser.
        """
        if (isinstance(wip_tree_item, RWipItem) or
                isinstance(wip_tree_item, RWipVersionItem)):
            self.on_open_clicked()
        else:
            index = wip_tree_item.index()
            expanded = (not self.wip_browser.wip_tree.isExpanded(index))
            self.wip_browser.wip_tree.setExpanded(index, expanded)

    def open_wip_browser(self):
        """
        Open the wip browser to select the scene file within.
        """
        self.wip_browser = DispatcherWipBrowser(parent=self)
        if self.wip_browser.exec_():
            self.wip_ctx = self.wip_browser.wip_ctx
            self.toplayout.scene_render_edit.setText(self.wip_ctx.get_default_scene_path())
        return self.wip_ctx

    def set_validations(self):
        """
        setValidations is a method of RSTDispatcher that ...
        This method sets up all appropriate validations for text fields.
        If a character is invalid, it will not be allowed in the text field.
        @returns: None
        @rtype:

        """

        #reg = QtCore.QRegExp("(\d+(\-\d*\,|\-\d+x\d*(\,|\, )))*")
        reg = QtCore.QRegExp("(\d+(,|\-\d+(,|x\d+,)))*")
        #105-110x2
        self.framerangevalidator = QtGui.QRegExpValidator(reg, self)

        reg = QtCore.QRegExp("\d+")
        self.digitvalidator = QtGui.QRegExpValidator(reg, self)

        reg = QtCore.QRegExp("\d{4}")
        self.digit4limitvalidator = QtGui.QRegExpValidator(reg, self)

        #to match between numbers 3000 to 5000
        #reg = QtCore.QRegExp("\b[3-5][0-9]{3}\b")

    def _setup_scene_for_existing_root(self):
        rsffile = self.root['filename']

        rsfcontext = path_extractor.extract(rsffile)
        try:
            index = self.sequence_name.findText(rsfcontext.sq)
        except:
            self.warning("This is not from the right show")
            return
        self.department = rsfcontext.department

        self.sequence_name.setCurrentIndex(index)
        index = self.shot_name.findText(rsfcontext.sh)
        self.shot_name.setCurrentIndex(index)
        self._update_scene_and_rsf(rsf_in=rsffile)
        if self._firsttime:
            self._load_passes()
            self._firsttime = False

    def _get_resolutions(self):
        """
        _get_resolutions is an internal method of RSTDispatcher that  ...
        sets up the top form gui with the show/seq/shot specific resolutions
        and modifies combobox on the fly.

        @returns: None
        @rtype:

        """
        # Get the resolution from the pipe object and generate double/half res
        render_res = self.pipe_obj.render.render_res
        half_res = Resolution(math.floor(render_res.x/2), math.floor(render_res.y/2), 'Half Res')
        double_res = Resolution(math.floor(render_res.x*2), math.floor(render_res.y*2), 'Double Res')
        # Request from lighting to have this resolution
        marketing_res = Resolution(4096, 4096, name='Marketing Res')
        # Need to discuss how custom resolutions would be handled
        custom_reslist = self.pipe_obj.render.get_custom_resolutions('lighting')
        reslist = [
            render_res,
            half_res,
            double_res,
            marketing_res,
        ]
        reslist.extend(custom_reslist)
        #res_xml = path_finder.get_configuration_file('resolution.xml', self.context)
        #tree = cElementTree.parse(res_xml)
        #reselement = tree.find('render')
        #reslist = list(reselement)

        self.toplayout.rescombo.clear()
        for item in reslist:
            tmpdict = {}
            tmpdict['renderWidth'] = str(item.width)
            tmpdict['renderHeight'] = str(item.height)
            tmpdict['renderAspect'] = str(item.aspect)
            tmpdict['name'] = item.name if item.name else ''
            #for attr in item.items():
                #if attr[0] == 'width':
                    #tmpdict['renderWidth'] = attr[1]
                #elif attr[0] == 'height':
                    #tmpdict['renderHeight'] = attr[1]
                #elif attr[0] == 'aspect':
                    #tmpdict['renderAspect'] = attr[1]
                #elif attr[0] == 'name':
                    #tmpdict['name'] = attr[1]

            #I'm storing the tmpdict inside a tuple because it is immutable,
            #otherwise everything gets turned into a qvariant, gross dude.
            self.toplayout.rescombo.addItem(tmpdict['renderWidth'] + " x " +
                                     tmpdict['renderHeight'] + " [" +
                                     tmpdict['renderAspect'] + "] " +
                                     tmpdict['name'],
                                     userData=(tmpdict,))

    def _perform_frame_range_action(self, action):
        """
        _perform_frame_range_action is an internal method of RSTDispatcher
        modifies the frame_range lineedit from a right click action.
        the default values are class wide stored from when the seq/shot
        is first specified

        @param action: The action that was right clicked
        @type action: a pyqt action
        @returns: None
        @rtype:

        """
        lineedit = action.parent().parent()
        process_loc = False
        eye = 0
        exrcheck=False
        if action.text() == "Default Range":
            if self.default_frame_range == "":
                self.statusbar.showMessage(
                                "No Default Frame Range set in insight", 5000)
            else:
                lineedit.setText(self.default_frame_range)
        elif action.text() == "Hero Frame":
            if self.hero_frame == "":
                self.statusbar.showMessage(
                                        "No Hero Frame set in insight", 5000)
            else:
                lineedit.setText(self.hero_frame)

        elif action.text() == "Key Frames":
            if self.key_frames == "":
                self.statusbar.showMessage(
                                        "No Key Frames set in insight", 5000)
            else:
                lineedit.setText(self.key_frames)

        elif action.text() == "Missing Frames (Left Eye)":
            eye=0
            process_loc = True
        elif action.text() == "Missing Frames (Right Eye)":
            eye=1
            process_loc = True
        elif action.text() == "Missing Frames (Both Eyes)":
            eye=2
            process_loc = True
        elif action.text() == "Missing/Incomplete exr Frames (Left Eye)":
            eye=0
            process_loc = True
            exrcheck=True
        elif action.text() == "Missing/Incomplete exr Frames (Right Eye)":
            eye=1
            process_loc = True
            exrcheck=True
        elif action.text() == "Missing/Incomplete exr Frames (Both Eyes)":
            eye=2
            process_loc = True
            exrcheck=True

        if process_loc:
            rownumber = None
            if not lineedit == self.br_frame_range:
                location = lineedit.click_location
                location = lineedit.mapToParent(location)

                rownumber = self.table.indexAt(location).row()

            temp = self.cursor()
            self.setCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            self._find_missing_frames(eye,rowindex=rownumber,checkifcomplete=exrcheck)
            self.setCursor(temp)


    def _set_frame_range(self):
        """
        _set_frame_range is an internal method of RSTDispatcher that  ...
        stores the default framerange values for the shot using the structure
        xml file.

        @returns:None
        @rtype:

        """
        index = self.sequence_name.currentIndex()
        shot = self.project_object.shots.where(
              sequence_id=str(self.sequence_name.itemData(index).toString()),
              name=str(self.shot_name.currentText())).first()

        seq = str(self.sequence_name.currentText())

        path = self.context.get_path('sh_info_dir')
        structure_xml = (path + "/" + seq + '_' +
                        str(self.shot_name.currentText()) + '_structure.xml')

        if os.path.isfile(structure_xml):
            tree = cElementTree.parse(structure_xml)
            root = tree.getroot()
            startframe = root.get('FrameRangeStart')
            endframe = root.get('FrameRangeEnd')
            self.default_frame_range = startframe + "-" + endframe
        else:
            self.default_frame_range = (str(shot.frame_range_start) + "-" +
                                         str(shot.frame_range_end))

        self.hero_frame = str(shot.hero_frame)
        self.key_frames = str(shot.key_frames)

        if self.default_frame_range == "None":
            self.default_frame_range = ""
        if self.hero_frame == "None":
            self.hero_frame = ""
        if self.key_frames == "None":
            self.key_frames = ""



    def _build_bottom_row(self):
        """
        _build_bottom_row is an internal method of RSTDispatcher that  ...
        Builds the bottom row of the dispatcher for modifying all rows in the
        table simultaneously.

        @returns:
        @rtype:

        """
        self.bottom_row_table = QtGui.QTableWidget(0, 13)
        self.bottom_row_table.horizontalHeader().hide()
        self.bottom_row_table.verticalHeader().hide()
        self.bottom_row_table.insertRow(0)
        self.bottom_row_table.setMaximumHeight(50)

        combo = QtGui.QComboBox()
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(220, 220, 220))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
        combo.setPalette(pal)
        self.populate_cameras(combo, allow_specification=True)

        br_pass = QtGui.QTableWidgetItem(" All Layers and Passes ")
        br_pass.setBackgroundColor(QtGui.QColor(220, 220, 220))
        br_pass.setForeground(QtGui.QColor("black"))
        br_pass.setFlags(QtCore.Qt.ItemIsEnabled)
        self.br_frame_range = MyLineEdit("")
        self.br_frame_range.setStyleSheet(self.sheet)
        self.br_frame_range.setValidator(self.framerangevalidator)
        self.connect(self.br_frame_range,
                     QtCore.SIGNAL('textChanged (const QString&)'),
                     self.signalmapper,
                     QtCore.SLOT("map()"))

        self.signalmapper.setMapping(self.br_frame_range, "bottom,2")
        frmenu = QtGui.QMenu(self.br_frame_range)
        frmenu.addAction("Default Range")
        frmenu.addAction("Hero Frame")
        frmenu.addAction("Key Frames")
        frmenu.insertSeparator(QtGui.QAction("", frmenu))
        frmenu.addAction("Missing Frames (Left Eye)")
        frmenu.addAction("Missing Frames (Right Eye)")
        frmenu.addAction("Missing Frames (Both Eyes)")
        frmenu.insertSeparator(QtGui.QAction("", frmenu))
        frmenu.addAction("Missing/Incomplete exr Frames (Left Eye)")
        frmenu.addAction("Missing/Incomplete exr Frames (Right Eye)")
        frmenu.addAction("Missing/Incomplete exr Frames (Both Eyes)")

        self.connect(frmenu,
                     QtCore.SIGNAL('triggered(QAction*)'),
                     self._perform_frame_range_action)

        self.br_frame_range.set_custom_context_menu(frmenu)

        # br_shotopt = RToggleButton(self.icondir + self._size + "tools.png", "")
        # self.connect(br_shotopt, QtCore.SIGNAL('clicked()'),
        #              self.signalmapper, QtCore.SLOT("map()"))
        # self.signalmapper.setMapping(br_shotopt, "bottom,4")

        br_l = RToggleButton(self.icondir + self._size +
                              "photo_camera_left.png", "")
        self.connect(br_l, QtCore.SIGNAL('clicked()'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_l, "bottom,5")

        br_r = RToggleButton(self.icondir + self._size +
                              "photo_camera_right.png", "")
        self.connect(br_r, QtCore.SIGNAL('clicked()'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_r, "bottom,6")

        br_up = RToggleButton(self.icondir + self._size +
                               "orange_arrow_up.png", "")
        br_up.setToolTip("Increase the render version")
        self.connect(br_up, QtCore.SIGNAL('clicked()'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_up, "bottom,7")

        br_camera = combo
        self.connect(br_camera, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_camera, "bottom,8")

        br_priority = QtGui.QLineEdit("3000")
        br_priority.setStyleSheet(self.sheet)
        br_priority.setMaximumWidth(70)
        br_priority.setValidator(self.digit4limitvalidator)
        self.connect(br_priority,
                     QtCore.SIGNAL('textEdited (const QString&)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_priority, "bottom,9")

        br_procs = QtGui.QLineEdit("10")
        br_procs.setStyleSheet(self.sheet)
        br_procs.setMaximumWidth(50)
        br_procs.setValidator(self.digit4limitvalidator)
        self.connect(br_procs, QtCore.SIGNAL('textEdited (const QString&)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_procs, "bottom,10")

        br_mantra_cluster = QtGui.QComboBox()
        self.populate_combo(br_mantra_cluster, field='mantra')
        self.connect(br_mantra_cluster, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_mantra_cluster, "bottom,11")

        br_hbatch_dist = QtGui.QComboBox()
        self.populate_combo(br_hbatch_dist, field='hbatch_dist')
        self.connect(br_hbatch_dist, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(br_hbatch_dist, "bottom,12")

        # br_playerbutton = QtGui.QPushButton(QtGui.QIcon(self.icondir +
        #                                         self._size + "film.png"), "")
        # br_playerbutton.setIconSize(QtCore.QSize(30, 30))
        # self.connect(br_playerbutton,
        #              QtCore.SIGNAL('clicked()'),
        #              self._play_comp)

        self.bottom_row_table.setItem(0, 0, br_pass)
        self.bottom_row_table.setCellWidget(0, 1, self.br_frame_range)
        blank = QtGui.QWidget()
        clear_link_button = QtGui.QPushButton(ui_lib_old.ui_utils.get_icon('brokenlink'), '')
        # blank.setFlags(QtCore.Qt.ItemIsEnabled)
        self.bottom_row_table.setCellWidget(0, 2, clear_link_button)
        self.connect(clear_link_button, QtCore.SIGNAL('clicked()'), self._clear_link_list)

        self.bottom_row_table.setCellWidget(0, 3, blank)
        # self.bottom_row_table.setCellWidget(0, 3, br_shotopt)
        self.bottom_row_table.setCellWidget(0, 4, br_l)
        self.bottom_row_table.setCellWidget(0, 5, br_r)
        self.bottom_row_table.setCellWidget(0, 6, br_up)
        self.bottom_row_table.setCellWidget(0, 7, br_camera)
        self.bottom_row_table.setCellWidget(0, 8, br_priority)
        self.bottom_row_table.setCellWidget(0, 9, br_procs)
        # self.bottom_row_table.setCellWidget(0, 10, br_playerbutton)
        # self.bottom_row_table.setCellWidget(0, 10, blank)
        self.bottom_row_table.setCellWidget(0, 10, br_mantra_cluster)
        self.bottom_row_table.setCellWidget(0, 11, br_hbatch_dist)

        self.bottom_row_table.resizeColumnsToContents()
        self.bottom_row_table.resizeRowsToContents()
        # self.bottom_row_table.setColumnWidth(2, 46)

        # self.bottom_row_table.setColumnWidth(2,0)
        self.bottom_row_table.setColumnWidth(3,0)
        self.bottom_row_table.setSelectionMode(
                                        QtGui.QAbstractItemView.NoSelection)

    def _build_bottom_buttons(self):
        """
        _build_bottom_buttons is an internal method of RSTDispatcher that  ...
        builds the bottom buttons in the GUI that represent submit, load rlc,
        clear passes, and close
        @returns: None
        @rtype:

        """
        self.bottom_button_layout = QtGui.QHBoxLayout()
        self.submit_all_button = QtGui.QPushButton("Submit All")
        self.load_rlc_layer_button = QtGui.QPushButton("Load RLC Layers")
        self.clear_layers_button = QtGui.QPushButton("Clear Layers")
        self.close_button = QtGui.QPushButton("Close")
        self.bottom_button_layout.addWidget(self.submit_all_button)
        self.bottom_button_layout.addWidget(self.load_rlc_layer_button)
        self.bottom_button_layout.addWidget(self.clear_layers_button)
        self.bottom_button_layout.addWidget(self.close_button)

        self.connect(self.submit_all_button, QtCore.SIGNAL('clicked()'),
                     self.submit_render)
        self.connect(self.load_rlc_layer_button, QtCore.SIGNAL('clicked()'),
                     self._load_passes)
        self.connect(self.clear_layers_button, QtCore.SIGNAL('clicked()'),
                     self._clear_passes)
        self.connect(self.close_button, QtCore.SIGNAL('clicked()'),
                     self.close)

    def _build_bottom_tab(self):
        """
        _build_bottom_tab is an internal method of RSTDispatcher that  ...
        builds the bottom tab containing the render notes and the render
        settings tabs

        @returns: None
        @rtype:

        """
        self.bottomtab = QtGui.QTabWidget(self)
        self.bottomtab.setMaximumHeight(200)

        self.log_edit = QtGui.QTextEdit("")
        self.log_edit.setReadOnly(True)
        self.note_edit = MyTextEdit("")
        self.note_edit.setToolTip("Right click me to view "
                                  "notes from previous renders!")
        self.bottomtab.addTab(self.log_edit, "Log")
        self.bottomtab.addTab(self.note_edit, "Notes")

        notemenu = QtGui.QMenu(self.note_edit)
        notemenu.addAction("View Notes")
        self.note_edit.set_custom_context_menu(notemenu)
        self.bottomtab2 = QtGui.QTabWidget(self)
        self.bottomtab.addTab(self.bottomtab2, "Render Settings")
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Button, QtGui.QColor(155, 155, 155))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
        self.bottomtab.setPalette(pal)
        self.bottomtab2.setPalette(pal)
        self.connect(notemenu, QtCore.SIGNAL('triggered(QAction*)'),
                      self._view_notes)

    def _view_notes(self):
        """
        _view_notes is an internal method of RSTDispatcher that  ...
        views the render note file in a qdialog.  The rendernotes file
        is per seq/shot

        @returns: None
        @rtype:

        """
        seq = self.sequence_name.currentText()
        shot = self.shot_name.currentText()
        try:
            rnotesfile = (self.context.get_path('sh_info_dir') + "/" +
                          str(seq + "_" + shot + '_renderNotes.txt'))
        except:
            self.statusbar.showMessage("You must select a seq/shot first",
                                        5000)
            return
        if os.path.isfile(rnotesfile):
            dialog = QtGui.QDialog(self)
            dialog.resize(700, 500)
            dialog.setWindowTitle("Note Viewer")
            dialog.setPalette(self.pal)
            widget = QtGui.QWidget(dialog)
            widget.setGeometry(QtCore.QRect(20, 10, 670, 490))
            gridLayout = QtGui.QGridLayout(widget)
            textedit = QtGui.QTextEdit(widget)
            pal = self.palette()
            pal.setColor(QtGui.QPalette.Base, QtGui.QColor(220, 220, 220))
            pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
            textedit.setPalette(pal)
            f = open(rnotesfile, 'r')
            textedit.setText(f.read())
            f.close()
            textedit.setReadOnly(1)
            gridLayout.addWidget(textedit, 0, 0, 1, 1)
            buttonBox = QtGui.QDialogButtonBox(widget)
            buttonBox.setOrientation(QtCore.Qt.Horizontal)
            buttonBox.setStandardButtons(QtGui.QDialogButtonBox.Ok)
            gridLayout.addWidget(buttonBox, 1, 0, 1, 1)

            QtCore.QObject.connect(buttonBox, QtCore.SIGNAL("accepted()"),
                                    dialog.accept)
            dialog.exec_()
        else:
            self.statusbar.showMessage("Render Notes file not found", 5000)

    def _write_notes(self, notes_list, notes_jobid_list, grpid):
        """
        _write_notes is an internal method of RSTDispatcher that  ...
        writes the dispatched job notes, it includes frameranges, passnames,
        job id, grp id and the notes that are written in by the user in the
        gui. The length of the notes_list and the jobid_list should match
        and be in the same order.

        @param notes_list:notes list contains the passname and framerange
        @type notes_list: list
        @param notes_jobid_list: contains the jobid
        @type notes_jobid_list: list
        @param grpid: group id if the render was submitted without shotopt
        @type grpid: string
        @returns: None
        @rtype:

        """
        seq = self.sequence_name.currentText()
        shot = self.shot_name.currentText()
        rnotesfile = (self.context.get_path('sh_info_dir') + "/" +
                      str(seq + "_" + shot + '_renderNotes.txt'))
        outputstring = "______________________________________________\n"
        outputstring += os.environ['USER'] + ", " + time.ctime() + "\n"
        outputstring += str(self.note_edit.toPlainText())
        outputstring += "\n\nScene: " + str(self.scene_render_edit.text())
        outputstring += "\nRSF: " + str(self.rst_rsf_edit.text())
        if not grpid == "":
            outputstring += "\n\nGroup id: " + grpid
        else:
            outputstring += "\n"
        outputstring += "\nLayers: \n\n"
        keylen = 0
        framelen = 0
        if not len(notes_list) == len(notes_jobid_list):
            self.warning("The notes list and the jobid list did not match\n" +
                         "Failed to write the notes"
                         " There are probably jobs that did not launch on the"
                         " farm (may be a qube traffic issue)")
            return 0

        for i in range(0, len(notes_list)):
            if len(notes_list[i][0]) > keylen:
                keylen = len(notes_list[i][0])
            if len(notes_list[i][1]) > framelen:
                framelen = len(notes_list[i][1])
        keylen += 2
        framelen += 2
        for i in range(0, len(notes_list)):
            spacer = (keylen - len(notes_list[i][0])) * " "
            spacer2 = (framelen - len(notes_list[i][1])) * " "
            outputstring += (notes_list[i][0] + spacer + "Frames: " +
                             notes_list[i][1] + spacer2 + "Job id: " +
                             str(notes_jobid_list[i]) + "\n")
        outputstring += "\n"
        if os.path.isfile(rnotesfile):
            infile = open(rnotesfile, "r")
            txt = infile.read()
            infile.close()
            outputstring += txt
            outfile = open(rnotesfile, "w")
            outfile.write(outputstring)
            outfile.close()
        else:
            outfile = open(rnotesfile, "w")
            outfile.write(outputstring)
            outfile.close()

    def _play_comp(self):
        """
        _play_comp is an internal method of RSTDispatcher that  ...
        plays the comp from the comp images dir, using rv
        if it can find them.

        @returns: None
        @rtype:

        """
        shot = str(self.shot_name.currentText())
        seq = str(self.sequence_name.currentText())
        context = PathContext(project=self.show_longname, disc='lit',
                              sequence=seq, shot=shot)
        imagepath = context.get_path('sh_comp_images_dir')
        imagepath += '/live'
        if os.path.isdir(imagepath):
            os.system('rv ' + imagepath + '/*')
        else:
            self.statusbar.showMessage("No comp images found", 5000)

    def _find_image_path(self, passname, passtype, eye):
        """
        _find_image_path is an internal method of RSTDispatcher that  ...
        finds the image path based on the passname, type of pass, and the eye

        @param passname: the name of the layer/pass
        @type passname: string
        @param passtype: what type of pass it is
        @type passtype: string
        @param eye: left right or both
        @type eye: int
        @returns: a tuple of the path to the parent directory, the left, and
                right image paths
        @rtype: tuple

        """
        shot = str(self.shot_name.currentText())
        seq = str(self.sequence_name.currentText())
        context = PathContext(project=self.show_longname,
                              disc='lit', sequence=seq, shot=shot)
        context['maya_file'] = str(self.scene_render_edit.text())[:-3].split(
                                                                    "/")[-1]
        context['rlc'] = str(self.rst_rsf_edit.text())[:-4].split("/")[-1]
        context['layer'] = str(passname)
        context['pass'] = str(passtype)
        imagepath = context.get_path('sh_render_layer_dir')
        imagepathtmp = imagepath
        if eye == 0:#Left
            eye = "l"
        elif eye == 1:#right
            eye = "r"
        else:#both
            imagepath += '/live/'
            imagetuple = (imagepathtmp, imagepath + "l/", imagepath + "r/")
            return imagetuple

        imagepath += '/live/' + eye + "/"
        return (imagepathtmp, imagepath)

    def _is_complete_exr(self,frame,path,mutex,missinglist):
        infile = OpenEXR.InputFile(path)
        if not infile.isComplete():
            mutex.lock()
            missinglist.append(int(frame))
            mutex.unlock()

    def _find_missing_frames(self,eye,rowindex=None, checkifcomplete=False):
        """
        _find_missing_frames is an internal method of RSTDispatcher that  ...
        Finds the missing frames from a selected layer.  If no row in the
        table is selected, it will run through all visible layers.  It will
        adhere to the frame ranges specified for each framerange text edit.

        @param eye: Which eye, 0 for left, 1 for right, 2 for both
        @type eye: int
        @param rowindex: The index of the layer in the self.table
        @type rowindex: int
        @returns: None
        @rtype:

        """
        model = self.table.model()
        layerlist=[]
        if rowindex is None:
            layerlist=range(0,self.table.rowCount())
            self.pbar.reset()
            self.statusbar.hide()
            self.pbar.show()
        else:
            layerlist.append(rowindex)


        increment = 100.0/len(layerlist)
        addup=0
        for row in layerlist:
            #This will keep the gui alive while chugging along
            QtGui.QApplication.processEvents()

            modelindex = model.index(row, 0)
            passname = str(self.table.itemFromIndex(modelindex).text())
            modelindex = model.index(row, 1)
            passtype = str(self.table.itemFromIndex(modelindex).text())
            pathtuple = self._find_image_path(passname, passtype, eye)

            framelist = self._frame_range_splitter(model.index(row, 2))
            comboindex = self.rescombo.currentIndex()
            format = self.output_format_combo.itemData(comboindex).toPyObject()[0]
            missinglist = []
            threadlist=[]
            mutex = QtCore.QMutex()
            for frame in framelist:
                fourframe = "%04d" % int(frame)
                path = (pathtuple[1] + passname + "_" +
                                       passtype + "." + fourframe +
                                       "." + format)
                if not os.path.isfile(path):
                    missinglist.append(int(frame))
                else:
                    if format == "exr" and checkifcomplete:
                        generic_thread = GenericThread(self._is_complete_exr,frame,path,mutex,missinglist)
                        threadlist.append(generic_thread)
                if len(pathtuple) > 2:
                    path2 = (pathtuple[2] + passname + "_" +
                                       passtype + "." + fourframe +
                                       "." + format)
                    if not os.path.isfile(path2):
                        missinglist.append(int(frame))
                    else:
                        if format == "exr" and checkifcomplete:
                            generic_thread = GenericThread(self._is_complete_exr,frame,path,mutex,missinglist)
                            threadlist.append(generic_thread)

            for thread in threadlist:
                thread.start()
            #remove duplicates
            missinglist = list(set(missinglist))

            result = ""
            if len(missinglist):
                result = self._ranges(missinglist)

            newstring = ""
            for sequences in list(result):
                    newstring += sequences + ","

            newstring = newstring.rstrip(",")
            modelindex = model.index(row, 2)
            self.table.indexWidget(modelindex).setText(newstring)
            self.table.cellWidget(row, 3).flatten_or_not(1)
            self.table.cellWidget(row, 6).flatten_or_not(1)

            self.table.cellWidget(row, 4).flatten_or_not(1)
            self.table.cellWidget(row, 7).flatten_or_not(1)
            if newstring == "":
                self.table.cellWidget(row, 5).flatten_or_not(1)
                self.table.cellWidget(row, 6).flatten_or_not(1)
            else:
                if eye == 0:
                    self.table.cellWidget(row, 5).flatten_or_not(0)
                    self.table.cellWidget(row, 6).flatten_or_not(1)
                elif eye == 1:
                    self.table.cellWidget(row, 5).flatten_or_not(1)
                    self.table.cellWidget(row, 6).flatten_or_not(0)
                else:
                    self.table.cellWidget(row, 5).flatten_or_not(0)
                    self.table.cellWidget(row, 6).flatten_or_not(0)

            if addup > 100:
                addup = 100
            self.pbar.setValue(int(addup))
            addup += increment


        self.statusbar.show()
        self.pbar.hide()

    def _ranges(self,framelist):
        sortedlist = sorted(framelist)
        i = 0
        newlist = []

        for k, g in itertools.groupby(enumerate(sortedlist), lambda (i,x):i-x):
            tmplist = map(operator.itemgetter(1), g)
            if len(tmplist) == 1:
                newlist.append(str(tmplist[0]))
            else:
                newlist.append(str(tmplist[0]) + "-" + str(tmplist[-1]))

        return newlist


    def _frame_range_splitter(self,modelindex):
        frame_range = str(self.table.indexWidget(modelindex).text())

        if frame_range == '':
            return []

        frame_range = frame_range.strip(' ')
        sections = frame_range.split(',')
        framerange = []
        for frames in sections:
            if 'x' in frames:
                first_range = int(frames.split('-')[0])
                last_range_x = frames.split('-')[1]
                last_range = int(last_range_x.split('x')[0])
                by_frame = int(last_range_x.split('x')[1])
                frame_range = range(first_range, last_range + 1)
                frame_range = frame_range[0:len(frame_range):by_frame]
                [framerange.append(str(f)) for f in frame_range]

            elif '-' in frames:
                first_range = int(frames.split('-')[0])
                last_range = int(frames.split('-')[1])
                [framerange.append(str(i)) for i in range(first_range,last_range+1)]

            else:
                framerange.append(frames)

        return framerange

    def _view_images(self, passname, passtype):
        """
        _view_images is an internal method of RSTDispatcher that  ...
        views the images found in the image path for the left eye
        it also will check the directory above for non standard locations of
        images.

        @param passname: the name of the pass
        @type passname: string
        @param passtype: the type of the pass
        @type passtype: string
        @returns: None
        @rtype:

        """
        imagetuple = self._find_image_path(passname, passtype, 0)
        left_imagepath = imagetuple[1]
        if os.path.isdir(left_imagepath):
            if len(glob.glob(left_imagepath + '/*')):
                #See if there are any files in here
                os.system('rv ' + left_imagepath + '/*')
            else:
                #Try the next level up
                os.system('rv ' + imagetuple[0] + '/*')
        else:
            self.statusbar.showMessage("No images found for that pass", 5000)

    def _add_new_render_setting(self, command, title):
        """
        _add_new_render_setting is an internal method of RSTDispatcher that
        will create a new text editor for the pass where override render
        settings was pushed.  A qmenu is set up for the text editor to allow
        you to clear the tab or load settings, which brings up some predefined
        render settings that are editable.

        @param command: usually blank
        @type command: string
        @param title: title of the pass and tab to be created
        @type title: string
        @returns: the newly created tab
        @rtype: qTabWidget

        """
        newrender = MyTextEdit(command)
        rsettingsmenu = QtGui.QMenu(newrender)
        rsettingsmenu.addAction("Load Render Settings")
        #rsettingsmenu.addAction("Load Sequence Settings")
        #rsettingsmenu.addAction("Load Project Settings")
        rsettingsmenu.insertSeparator(QtGui.QAction("", rsettingsmenu))
        rsettingsmenu.addAction("Delete Render Settings")
        newrender.set_custom_context_menu(rsettingsmenu)
        self.connect(rsettingsmenu, QtCore.SIGNAL('triggered(QAction*)'),
                      self._load_render_settings)
        return self.bottomtab2.addTab(newrender, title)

    def _load_render_settings(self, action):
        """
        _load_render_settings is an internal method of RSTDispatcher that  ...
        load the customizable render settings from the seq/shot structure.
        It checks the renderSettings.txt for those.

        @param action: The action that was right clicked, so it knows which
        tab to insert text into.
        @type action: QAction
        @returns: None
        @rtype:

        """
        # Previously the render settings were extracting from a txt file.
        textedit = action.parent().parent()
        # How should we load render settings for this new method?
        if action.text() == "Load Render Settings":
            rsettingsfile = 'not/a/file'
            #rsettingsfile = path_finder.get_configuration_file('renderSettings.txt', self.context)
            if os.path.isfile(rsettingsfile):
                f = open(rsettingsfile, 'r')
                textedit.setText(f.read())
                f.close()
            else:
                self.statusbar.showMessage("Render Settings file not found",
                                            5000)
        elif action.text() == "Delete Render Settings":
            index = textedit.parent().currentIndex()
            self.tab2list.remove(self.bottomtab2.tabText(index))
            self.bottomtab2.removeTab(textedit.parent().currentIndex())

    # XXX TODO: This should be removed
    def _open_scene_render_dialog(self):
        """
        _open_scene_render_dialog is an internal method of RSTDispatcher that
        Opens the file dialog for the scene renderer.

        @returns: None
        @rtype:

        """
        txt = self.toplayout._scene_filedialog.getOpenFileNameAndFilter(
                                directory=self.toplayout.scene_render_edit.text(),
                                filter="Maya ascii/binary (*.ma *.mb)")[0]
        if txt:
            self.toplayout.scene_render_edit.setText(txt)
        else:
            self._test_for_unlock()

    def _open_rst_filedialog(self):
        """
        _open_rst_filedialog is an internal method of RSTDispatcher that  ...
        Opens the file dialog for the rsf files.

        @returns: None
        @rtype:

        """
        txt = self.toplayout._rst_filedialog.getOpenFileNameAndFilter(
                                directory=self.toplayout.rst_rsf_edit.text(),
                                filter="RST files (*.rsf)")[0]
        if txt:
            self.toplayout.rst_rsf_edit.setText(txt)
            self._load_passes()
        else:
            self._test_for_unlock()

    def _write_shot_history(self, index, update=True):
        """
        _write_shot_history is an internal method of RSTDispatcher that  ...
        stores the history of what seq/shots have been opened in this session.
        The method will add new actions to the button on the right of the shot
        menu to give you a shortcut to old jobs selected for rendering.
        If update is selected, The information in the scene and rsf will
        attempt to populate itself. If the text already exists, it will return
        before any gui changes are made.

        @param index: The index of the shot selected
        @type index: int
        @param update: choose to update the scene and rsf Qlineedits
        @type update: boolean
        @returns: None
        @rtype:

        """
        if self.seq_chg:
            self.seq_chg = False
            return
        seq_txt = self.sequence_name.currentText()
        if seq_txt == "":
            return
        shot_txt = self.shot_name.itemText(index)
        if shot_txt == "":
            return

        for items in self.actionhistory:
            if seq_txt + "_" + shot_txt == items[1]:
                return

        if update:
            self._update_scene_and_rsf()

        txt = seq_txt + "_" + shot_txt
        newact = QtGui.QAction(txt, None)
        newact.setData(txt)

        self.actionhistory.insert(0, (newact, txt))
        if len(self.actionhistory) == 5:
            self.shot_qmenu.removeAction(self.actionhistory.pop()[0])

        self.shot_qmenu.insertAction(self.actionhistory[1][0],
                                     self.actionhistory[0][0])

    def _lock_bottom_buttons(self):
        """
        _lock_bottom_buttons is an internal method of RSTDispatcher that  ...
        Disables the bottom buttons so a person cannot accidentally render
        with misinformation filled out in the top form.

        @returns: None
        @rtype:

        """
        self.submit_all_button.setDisabled(1)
        self.submit_all_button.setFlat(1)
        self.load_rlc_layer_button.setDisabled(1)
        self.load_rlc_layer_button.setFlat(1)
        self.br_frame_range.setDisabled(1)

    def _unlock_bottom_buttons(self):
        """
        _unlock_bottom_buttons is an internal method of RSTDispatcher that  ..
        The inverse of the lock button that allows submission and loading of
        the rsf files

        @returns: None
        @rtype:

        """
        self.submit_all_button.setDisabled(0)
        self.submit_all_button.setFlat(0)
        self.load_rlc_layer_button.setDisabled(0)
        self.load_rlc_layer_button.setFlat(0)
        self.br_frame_range.setDisabled(0)

    # XXX IS THIS NECESSARY?
    #def _set_project_xml(self):
        #"""
        #_set_project_xml is an internal method of RSTDispatcher that  ...
        #creates a proj_xml_tree that already contains the information in the
        #project xml if a future programmer needs information from the
        #project.xml that is not already included.

        #@returns: None
        #@rtype:

        #"""
        #proj_xml = path_finder.get_configuration_file('project.xml',
                                                       #self.context)
        #self.proj_xml_tree = cElementTree.parse(proj_xml)

    def _update_globalstereobool(self):
        """
        _update_globalstereobool is an internal method of RSTDispatcher that
        sets the string value for a class wide variable to track the stereo
        text.

        @returns: None
        @rtype:

        """
        # XXX THIS MAY NOT BE NECESSARY ANYMORE
        stereoelement = 1 #self.proj_xml_tree.find('stereo')
        self.globalstereobool = stereoelement.text

    def _update_scene_and_rsf(self, scene=None, rsf_in=None):
        """
        _update_scene_and_rsf is an internal method of RSTDispatcher that  ...
        updates all the information in the top form using the value of
        the sequence and shot to derive the info. It will set various class
        wide variables (default ranges, resolutions, reload the project xml
        tree, etc.)  It will then populate the scene and rsf qlineedits.

        @param scene:
        @type scene:
        @returns:
        @rtype:

        """
        sh = str(self.shot_name.currentText())
        seq = str(self.sequence_name.currentText())
        self.context = PathContext(department=self.department,
                                   shot=sh,
                              sequence=seq,
                              project=self.show_longname)
        self._get_resolutions()
        self._set_frame_range()
        #self._set_project_xml()
        self._update_globalstereobool()

        # SHOULD BE FOR HOUDINI
        malist = glob.glob(self.context.get_path('sh_lit_dir') + '/*.ma')

        if scene and os.path.isfile(scene):
            self.scene_render_edit.setText(scene)
        else:
            if len(malist) == 1:
                self.scene_render_edit.setText(malist[0])
            else:
                self.scene_render_edit.setText(self.context.get_path(
                                                                'sh_lit_dir'))
                filetest = (self.context.get_path('sh_lit_dir') + "/" +
                            seq + "_" + sh + "_lit.ma")
                if os.path.isfile(filetest):
                    self.scene_render_edit.setText(filetest)
                elif len(malist) > 1:
                    self._open_scene_render_dialog()

        if rsf_in:
            self.rst_rsf_edit.setText(rsf_in)
        else:
            rsflist = glob.glob(self.context.get_path('sh_rlc_dir') + '/*.rsf')
            if len (rsflist) == 1:
                self.rst_rsf_edit.setText(rsflist[0])
                self._load_passes()

            else:
                self.rst_rsf_edit.setText(self.context.get_path('sh_rlc_dir'))
                filetest = (self.context.get_path('sh_rlc_dir') + "/" + seq +
                             "_" + sh + "_rlc.rsf")
                if os.path.isfile(filetest):
                    self.rst_rsf_edit.setText(filetest)
                    msg_box = QtGui.QMessageBox()
                    msg_box.setPalette(self.pal)
                    msg_box.setText("I found a default rsf file,"
                                    " should I load that one?")
                    msg_box.setStandardButtons(
                                    QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
                    msg_box.setDefaultButton(QtGui.QMessageBox.No)
                    ret = msg_box.exec_()
                    if ret == QtGui.QMessageBox.Yes:
                        self._load_passes()
                    else:
                        self._open_rst_filedialog()

                elif len(rsflist) > 1:
                    self._open_rst_filedialog()

        #self.scene_render_edit.emit(QtCore.SIGNAL('editingFinished()'))
        #self.rst_rsf_edit.emit(QtCore.SIGNAL('editingFinished()'))



    def _load_shots_from_seq(self, index):
        """
        _load_shots_from_seq is an internal method of RSTDispatcher that  ...
        populates the shot qcombo box from insight after a sequence has been
        chosen.

        @param index: the index of the seq chosen
        @type index: int
        @returns: None
        @rtype:

        """
        self.shot_name.clear()
        self.seq_chg = True
        # Uses the old pipeline way to get the shots.  Use new way
        for shot_item in self.project_object.shots.where(sequence_id=str(
                self.sequence_name.itemData(index).toString())).order("name"):
            self.shot_name.addItem(str(shot_item.name), shot_item.id)

        self.shot_name.emit(QtCore.SIGNAL('activated(int)'), 0)

    def _clear_passes(self):
        """
        _clear_passes is an internal method of RSTDispatcher that  ...
        clears all the passes in the table.

        @returns: None
        @rtype:

        """
        self.table.clearContents()
        for rows in range(self.table.rowCount(), 0):
            self.table.removeRows(rows)
        self.table.setRowCount(0)
        self.bottomtab2.clear()
        self.tab2list = []
        self.linkedrowlist = []
        self.bottomtab.widget(0).clear()
        self.bottomtab.setCurrentIndex(0)

    def _clear_link_list(self):
        """
        _clear_link_list is an internal method of RSTDispatcher that  ...
        clears all the links that have been selected for each pass in the main
        table.

        @returns: None
        @rtype:

        """
        for i in self.linkedrowlist:
            self.table.cellWidget(i, 3).flatten_or_not(1)
        self.linkedrowlist = []

    def _modify_selections(self):
        """
        _modify_selections is an internal method of RSTDispatcher that  ...
        deselects a parent element of the pass selection tree if it is
        expanded.  This is to prevent bringing all the child passes in by
        accident, when not all of them are desired.

        @returns: None
        @rtype:

        """
        for items in self.tree.selectedItems():
            if not items.parent():
                if items.isExpanded():
                    items.setSelected(0)

    def _load_passes(self):
        """
        _load_passes is an internal method of RSTDispatcher that  ...
        populates the central table with all passes selected from the pass
        selection tree dialog.  It will test the rsf file first. Then create
        the tree dialog for user selection. Then populate the main table.

        @returns: None
        @rtype:

        """
        tempcursor = self.cursor()
        self.setCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))

        passgrps = self.root.find(type="PassGroup")
        if len(passgrps) == 0:
            self.statusbar.showMessage(
                "I could not find any pass groups in that rsf file", 10000)
        elif len(passgrps) == 1:
            name = passgrps[0].get_name()
            #return that pass here

        self._clear_passes()
        dialog = QtGui.QDialog(self)
        dialog.resize(503, 478)
        dialog.setWindowTitle("Select Your Passgroups")
        dialog.setPalette(self.pal)
        widget = QtGui.QWidget(dialog)
        widget.setGeometry(QtCore.QRect(20, 10, 458, 461))
        gridLayout = QtGui.QGridLayout(widget)
        self.tree = QtGui.QTreeWidget(widget)
        self.tree.setSelectionMode(QtGui.QAbstractItemView.MultiSelection)
        self.tree.setColumnCount(1)
        self.tree.header().hide()
        self.tree.setToolTip("Light grey entries mean "
                             "the pass is NOT approved")
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(180, 180, 180))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
        self.tree.setPalette(pal)
        gridLayout.addWidget(self.tree, 0, 0, 1, 1)
        buttonBox = QtGui.QDialogButtonBox(widget)
        buttonBox.setOrientation(QtCore.Qt.Horizontal)
        buttonBox.setStandardButtons(
                    QtGui.QDialogButtonBox.Cancel | QtGui.QDialogButtonBox.Ok)
        gridLayout.addWidget(buttonBox, 1, 0, 1, 1)

        QtCore.QObject.connect(self.tree,
                            QtCore.SIGNAL("itemExpanded (QTreeWidgetItem *)"),
                            self._modify_selections)
        QtCore.QObject.connect(self.tree,
                               QtCore.SIGNAL("itemSelectionChanged()"),
                               self._modify_selections)
        QtCore.QObject.connect(buttonBox, QtCore.SIGNAL("accepted()"),
                               dialog.accept)
        QtCore.QObject.connect(buttonBox, QtCore.SIGNAL("rejected()"),
                               dialog.reject)

        counter = 0
        for passgrp in passgrps:
            grpname = passgrp.get_name()
            lvi = QtGui.QTreeWidgetItem(self.tree)

            lvi.setText(0, grpname)
            for child in passgrp.get_children():
                pass_set = child.get_attribute('pass_settings')

                name = child.get_name()
                passtype = child.pass_type
                leaf = QtGui.QTreeWidgetItem(lvi)
                leaf.setText(0, name)
                leaf.setData(0, QtCore.Qt.UserRole, name)
                # NO STATUS IN PASS_SET
                # if pass_set.find('Status')[0].value[1].name == "approved":
                #     if not pass_set.find('Status')[0].value[1].value:
                #         leaf.setBackground(0, QtGui.QRadialGradient())
                #     else:
                #         leaf.setText(0, name + " (approved)")
                #         #Re-enable this if you want to see approved layers
                #         leaf.setDisabled(1)

                lvi.addChild(leaf)
            counter += 1
        self.tree.sortItems(0, 0)
        self.tree.sortItems(1, 0)
        val = dialog.exec_()
        if not val:
            self.setCursor(tempcursor)
            return 0

        self.passesgroup = []
        self.passeslist = []
        for index in self.tree.selectedIndexes():
            treeitem = self.tree.itemFromIndex(index)
            if not treeitem.parent():
                self.passesgroup.append(str(treeitem.text(0)))
            else:
                self.passeslist.append(treeitem)

        self.parentnames = {}
        for kids in self.passeslist:
            try:
                self.parentnames[str(kids.parent().text(0))].append(
                                            kids.data(0, QtCore.Qt.UserRole))
            except:
                self.parentnames[str(kids.parent().text(0))] = []
                self.parentnames[str(kids.parent().text(0))].append(
                                            kids.data(0, QtCore.Qt.UserRole))
        self.protectedlist = []
        self.approvedlist = []
        self.passdict = {}

        self.br_frame_range.setText(self.default_frame_range)
        self.br_frame_range.setToolTip("You can right click me\nor you can "
                                       "use 101-115x5 to render on 5s\nany "
                                       "number will work after the x!")

        for passgrp in passgrps:
            if passgrp.get_name() in self.passesgroup:
                for child in passgrp.get_children():
                    pass_set = child.get_attribute('pass_settings')
                    status = ""
                    customrange = ""
                    protect = 0
                    # When the range is locked, do not use
                    # the frame range, when it is unlocked, use it.
                    if pass_set.find('frameRange'):
                        pass_framerange = pass_set.find('frameRange')[0]
                        if not pass_framerange.locked:
                            customrange = pass_framerange.value
                        else:
                            customrange = str(self.pipe_obj.get_frame_range())
                    # if pass_set.find('Range')[0].value[0].name == "customRange":
                    #     if pass_set.find('Range')[0].value[1].value:
                    #         customrange = pass_set.find('Range')[0].value[1].value
                    # if pass_set.find('Status')[0].value[1].name == "approved":
                    #     if pass_set.find('Status')[0].value[1].value:
                    #         status = "approved"
                    #         continue
                    # if pass_set.find('Status')[0].value[0].name == "protectShotOpt":
                    #     if pass_set.find('Status')[0].value[0].value:
                    #         protect = True
                    name = child.get_name()
                    passtype = child.pass_type
                    sources = child.get_children()
                    cameralist = [tmp for tmp in sources if tmp.source_type == 'camera']
                    self._make_new_layer_row(name, passtype, status,
                                             protect, customrange, cameralist)
                    self.passdict[name + "_" + passtype] = child

            elif passgrp.get_name() in self.parentnames.keys():
                for child in passgrp.get_children():
                    pass_set = child.get_attribute('pass_settings')
                    status = ""
                    customrange = ""
                    protect = 0
                    # RANGE AND STATUS NOT YET DEFINED
                    # if pass_set.find('Range')[0].value[0].name == "customRange":
                    #     if pass_set.find('Range')[0].value[1].value:
                    #         customrange = pass_set.find('Range')[0].value[1].value
                    # if pass_set.find('Status')[0].value[1].name == "approved":
                    #     if pass_set.find('Status')[0].value[1].value:
                    #         status = "approved"
                    #         continue
                    # if pass_set.find('Status')[0].value[0].name == "protectShotOpt":
                    #     if pass_set.find('Status')[0].value[0].value:
                    #         protect = True
                    name = child.get_name()
                    passtype = child.pass_type
                    sources = child.get_children()
                    cameralist = [tmp for tmp in sources if tmp.source_type == 'camera']
                    if name in self.parentnames[passgrp.get_name()]:
                        self._make_new_layer_row(name, passtype, status,
                                            protect, customrange, cameralist)
                        self.passdict[name + "_" + passtype] = child

        if self.inmaya:
            self.bottom_row_table.setColumnWidth(0, self.table.columnWidth(0)
                                            + self.table.columnWidth(1) + 13)
        else:
            self.bottom_row_table.setColumnWidth(0, self.table.columnWidth(0)
                                            + self.table.columnWidth(1) + 23)
        self.bottom_row_table.setColumnWidth(1, self.table.columnWidth(2))
        self._test_for_unlock()
        tmpstr = ""
        if len(self.protectedlist):
            tmpstr = "\nProtected shot opts:\n"
            for layers in self.protectedlist:
                tmpstr += layers + "\n"
        if len(self.approvedlist):
            tmpstr += "\nApproved passes:\n"
            for layers in self.approvedlist:
                tmpstr += layers + "\n"

        if not tmpstr == "":
            self.warning("These passes have "
                         "protected shotopts:\n" + tmpstr)
        self.setCursor(tempcursor)

    def _test_for_unlock(self):
        """
        _test_for_unlock is an internal method of RSTDispatcher that  ...
        makes sure the scene_render file and the rsf file are both valid files

        @returns: None
        @rtype:

        """
        if os.path.isfile(str(self.wip_ctx.get_default_scene_path())):
            self._unlock_bottom_buttons()
            return
        self._lock_bottom_buttons()

    def _modify_link_list(self, cellstring):
        """
        _modify_link_list is an internal method of RSTDispatcher that  ...
        is called by an action mapper.  The cellstring just identifies which
        layer and cell was modified, and then additionally modifies
        any cells linked with that one.  If the change is made in the bottom
        row, it affects all of the layers.

        @param cellstring: comma separated value row,column (bottom row has
                                                            its own entry)
        @type cellstring: string
        @returns: None
        @rtype:

        """
        splitter = cellstring.split(",")
        row = splitter[0]
        column = int(splitter[1])
        if row == "bottom":
            bottom = 0
            widget = self.bottom_row_table.cellWidget(bottom, column - 1)
            classname = widget.metaObject().className()
            info = ""
            if classname == "RToggleButton":
                info = widget.isFlat()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).flatten_or_not(info)
            elif classname == "MyLineEdit":
                info = widget.text()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setText(info)
            elif classname == "QComboBox":
                info = widget.currentIndex()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setCurrentIndex(info)
            elif classname == "QLineEdit":
                info = widget.text()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setText(info)

        else:
            row = int(row)
            # if column == 11:
            #     widget = self.table.item(row, 0)
            #     widget2 = self.table.item(row, 1)
            #     self._view_images(widget.text(), widget2.text())
            if column == 12:
                widget = self.table.item(row, 0)
                if widget.text() in self.tab2list:
                    return
                index = self._add_new_render_setting("", widget.text())
                self.bottomtab.setCurrentIndex(1)
                self.bottomtab2.setCurrentIndex(index)
                self.tab2list.append(widget.text())
            elif column == 3:
                flat = self.table.cellWidget(row, column).isFlat()
                try:
                    self.linkedrowlist.remove(row)
                except:
                    pass
                if not flat:
                    self.linkedrowlist.append(row)

            else:
                if row in self.linkedrowlist:
                    widget = self.table.cellWidget(row, column)
                    classname = widget.metaObject().className()
                    info = ""
                    if classname == "RToggleButton":
                        info = widget.isFlat()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i,
                                                column).flatten_or_not(info)
                    elif classname == "MyLineEdit":
                        info = widget.text()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i, column).setText(info)
                    elif classname == "QComboBox":
                        info = widget.currentIndex()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i,
                                                column).setCurrentIndex(info)
                    elif classname == "QLineEdit":
                        info = widget.text()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i, column).setText(info)

    def _make_new_layer_row(self, name, passtype, status, protect,
                             customrange, cameralist):
        """
        _make_new_layer_row is an internal method of RSTDispatcher that  ...
        populates a brand new row to be entered into the main table

        @param name: name of the layer
        @type name: string
        @param passtype: pass type
        @type passtype: string
        @param status: the status of the pass
        @type status: string
        @param protect: is the shotopt protected
        @type protect: boolean
        @param customrange: the custom range loaded in the rst pass
        @type customrange: string
        @param cameralist: list of cameras from the rst pass
        @type cameralist: list
        @returns: None
        @rtype:

        """
        row = self.table.rowCount()
        self.table.insertRow(row)
        table_layer = QtGui.QTableWidgetItem(name)
        table_layer.setBackgroundColor(QtGui.QColor(220, 220, 220))
        table_layer.setForeground(QtGui.QColor("black"))
        table_layer.setFlags(QtCore.Qt.ItemIsEnabled)
        table_pass = QtGui.QTableWidgetItem(passtype)
        table_pass.setBackgroundColor(QtGui.QColor(220, 220, 220))
        table_pass.setForeground(QtGui.QColor("black"))
        table_pass.setFlags(QtCore.Qt.ItemIsEnabled)
        model = self.table.model()
        table_frame_range = MyLineEdit("")
        table_frame_range.setStyleSheet(self.sheet)
        self.connect(table_frame_range,
                     QtCore.SIGNAL('textEdited (const QString&)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_frame_range, str(row) + ",2")

        frmenu = QtGui.QMenu(table_frame_range)
        frmenu.addAction("Default Range")
        frmenu.addAction("Hero Frame")
        frmenu.addAction("Key Frames")
        frmenu.insertSeparator(QtGui.QAction("", frmenu))
        frmenu.addAction("Missing Frames (Left Eye)")
        frmenu.addAction("Missing Frames (Right Eye)")
        frmenu.addAction("Missing Frames (Both Eyes)")
        frmenu.insertSeparator(QtGui.QAction("", frmenu))
        frmenu.addAction("Missing/Incomplete exr Frames (Left Eye)")
        frmenu.addAction("Missing/Incomplete exr Frames (Right Eye)")
        frmenu.addAction("Missing/Incomplete exr Frames (Both Eyes)")

        self.connect(frmenu, QtCore.SIGNAL('triggered(QAction*)'),
                     self._perform_frame_range_action)
        table_frame_range.setToolTip("You can right click me\nor you can "
                                     "use 101-115x5 to render on 5s\nany "
                                     "number will work after the x!")

        table_frame_range.set_custom_context_menu(frmenu)
        table_frame_range.setValidator(self.framerangevalidator)
        table_frame_range_button = QtGui.QPushButton()
        table_frame_range_button.setMaximumWidth(39)

        table_link = RToggleButton(self.icondir + self._size + "link.png", "")
        table_link.set_disabled_icon(self.icondir + self._size +
                                    "brokenlink.png")
        table_link.click()
        self.connect(table_link, QtCore.SIGNAL('clicked()'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_link, str(row) + ",3")

        # table_shotopt = RToggleButton(self.icondir + self._size + "tools.png",
        #                                "")
        # self.connect(table_shotopt, QtCore.SIGNAL('clicked()'),
        #               self.signalmapper, QtCore.SLOT("map()"))
        # self.signalmapper.setMapping(table_shotopt, str(row) + ",4")
        table_l = RToggleButton(self.icondir + self._size +
                                 "photo_camera_left.png", "")
        self.connect(table_l, QtCore.SIGNAL('clicked()'),
                      self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_l, str(row) + ",5")
        table_r = RToggleButton(self.icondir + self._size +
                                 "photo_camera_right.png", "")
        self.connect(table_r, QtCore.SIGNAL('clicked()'), self.signalmapper,
                      QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_r, str(row) + ",6")
        table_up = RToggleButton(self.icondir + self._size +
                                 "orange_arrow_up.png", "")
        self.connect(table_up, QtCore.SIGNAL('clicked()'), self.signalmapper,
                     QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_up, str(row) + ",7")
        table_up.setToolTip("Increase the render version")

        camcombo = QtGui.QComboBox()
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(220, 220, 220))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
        camcombo.setPalette(pal)
        self.populate_cameras(camcombo)

        if self.globalstereobool:
            camcombo.setCurrentIndex(1)

        tmpcamlist = []
        for cam in cameralist:
            tmpcamlist.append(cam.get_name())

        if len(tmpcamlist) > 1:
            camcombo.insertSeparator(2)
            tmpcamlist.sort()

        for cams in tmpcamlist:
            camcombo.addItem(cams)

        setindex = camcombo.findText(name)

        if setindex==-1:
            setindex = 0

        camcombo.setCurrentIndex(setindex)

        self.connect(camcombo, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(camcombo, str(row) + ",8")

        if status == "approved":
            # table_shotopt.click()
            table_l.click()
            table_r.click()
            table_up.click()
            self.approvedlist.append(name)

        if protect:
            # table_shotopt.flatten_or_not(1)
            self.protectedlist.append(name)

        if customrange:
            table_frame_range.setText(customrange)
        else:
            table_frame_range.setText(str(self.pipe_obj.get_frame_range()))

        table_priority = QtGui.QLineEdit("3000")
        table_priority.setStyleSheet(self.sheet)
        table_priority.setMaximumWidth(70)
        table_priority.setValidator(self.digit4limitvalidator)
        self.connect(table_priority,
                     QtCore.SIGNAL('textEdited (const QString&)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_priority, str(row) + ",9")
        table_procs = QtGui.QLineEdit("10")
        table_procs.setStyleSheet(self.sheet)
        table_procs.setMaximumWidth(50)
        table_procs.setValidator(self.digit4limitvalidator)
        self.connect(table_procs,
                     QtCore.SIGNAL('textEdited (const QString&)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(table_procs, str(row) + ",10")
        # Mantra Cluster
        mc_combo = QtGui.QComboBox()
        mc_combo.setPalette(pal)
        self.populate_combo(mc_combo, field='mantra')
        self.connect(mc_combo, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(mc_combo, str(row) + ",11")

        # Hbatch Distribution
        hd_combo = QtGui.QComboBox()
        hd_combo.setPalette(pal)
        self.populate_combo(hd_combo, field='hbatch_dist')
        self.connect(hd_combo, QtCore.SIGNAL('activated(int)'),
                     self.signalmapper, QtCore.SLOT("map()"))
        self.signalmapper.setMapping(hd_combo, str(row) + ",12")
        # playerbutton = QtGui.QPushButton(QtGui.QIcon(self.icondir +
        #                                              self._size + "film.png"),
        #                                               "")
        # playerbutton.setIconSize(QtCore.QSize(30, 30))
        # self.connect(playerbutton, QtCore.SIGNAL('clicked()'),
        #              self.signalmapper, QtCore.SLOT("map()"))
        # self.signalmapper.setMapping(playerbutton, str(row) + ",11")
        # table_override_render = QtGui.QPushButton("Override \nRender Settings")
        # self.connect(table_override_render, QtCore.SIGNAL('clicked()'),
        #              self.signalmapper, QtCore.SLOT("map()"))
        # self.signalmapper.setMapping(table_override_render, str(row) + ",12")

        blank = QtGui.QWidget()
        self.table.setItem(row, 0, table_layer)
        self.table.setItem(row, 1, table_pass)
        self.table.setCellWidget(row, 2, table_frame_range)
        self.table.setCellWidget(row, 3, table_link)
        # self.table.setCellWidget(row, 4, table_shotopt)
        self.table.setCellWidget(row, 4, blank)
        self.table.setCellWidget(row, 5, table_l)
        self.table.setCellWidget(row, 6, table_r)
        self.table.setCellWidget(row, 7, table_up)
        self.table.setCellWidget(row, 8, camcombo)
        self.table.setCellWidget(row, 9, table_priority)
        self.table.setCellWidget(row, 10, table_procs)
        # self.table.setCellWidget(row, 11, playerbutton)
        self.table.setCellWidget(row, 11, mc_combo)
        self.table.setCellWidget(row, 12, hd_combo)
        # self.table.setCellWidget(row, 12, table_override_render)
        self.table.setColumnWidth(4, 0)
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.table.setSelectionMode(QtGui.QAbstractItemView.NoSelection)

    def _build_help_menu(self, menubar):
        """
        _build_help_menu is an internal method of RSTDispatcher that  ...
        Builds the help menu for the top of the rstDispatcher

        @param menubar: The existing top menu bar
        @type menubar: QMenuBar
        @returns: None
        @rtype:

        """
        help_menu = QtGui.QMenu('Help')
        action = help_menu.addAction('Open documentation in Pages...',
                                     self.open_pages_link)
        action.setIcon(ui_lib_old.ui_utils.get_icon('globe'))

        help_menu.addSeparator()
        action = help_menu.addAction('About RST Dispatcher...', self.about)
        action.setIcon(ui_lib_old.ui_utils.get_icon('help'))
        menubar.addMenu(help_menu)
        self.help_menu = help_menu

    def open_pages_link(self):
        """
        open_pages_link is a method of RSTDispatcher that ...
        Opens the help doc for the dispatcher

        @returns: None
        @rtype:

        """
        webbrowser.open("http://pages.reelfx.com/lighting/"
                        "tools/render-tools/render-dispatcher")

    def about(self):
        """
        about is a method of RSTDispatcher that ...
        pops up a dialog containing the creater information

        @returns: None
        @rtype:

        """
        msg = ('RST PyDispatcher\n\n'
               'by Gates Roberg-Clark and Chris Penny\n\n'
               'based on work by Brandon Harris and John Anderholm\n')
        widgets.info(msg)

    # Use browser code
    def browser(self, browser_class, callback):
        parent = self
        browser = browser_class(parent=parent)
        if browser.exec_():
            response = callback(browser.path_ctx)
        else:
            response = Warning('Action Cancelled')
        return response

    def open_browser(self):
        return self.browser(file_browsers.Open, self.open_)

    def open_(self, path_ctx):
        # XXX TODO change later
        #response = None
        #response = self.prompt_to_save()
        response = lightning.groups.root.Root.from_path_context(path_ctx)
        #self.set_status(response)
        if not response.is_success():
            response.raise_exception()
        else:
            self.root = response.payload
            self.path_ctx = path_ctx
            self._load_passes()
            name = self.path_ctx.get('name')
            pipe_ctx = PipeContext.from_path_context(self.path_ctx)
            label = '%s (%s)' % (name, pipe_ctx)
            self.toplayout.rst_edit.setText(label)
        #if response.is_success():
            # XXX TODO Add this function
            #self.add_to_recents(path_ctx)
            #filename = path_ctx.get_path('rst_file')
            # self.set_status('Opening "%s"' % filename)
            #self.root(path_ctx=path_ctx)
            # self.update_title()
            # self.clear_ui()
            # self.refresh_all()
            # self.set_status('Done Opening "%s"' % filename)
            #response = Success('Open Successful: %s' % filename)
        return response

    def prompt_to_save(self):
        response = Success()
        if self.root().get_changes():
            message_box = QtGui.QMessageBox(parent=self)
            message_box.setIcon(QtGui.QMessageBox.Warning)
            message_box.setText('The document has been modified.')
            message_box.setInformativeText('Do you want to save your changes?')
            message_box.setStandardButtons(QtGui.QMessageBox.Save |
                                           QtGui.QMessageBox.Discard |
                                           QtGui.QMessageBox.Cancel);
            message_box.setDefaultButton(QtGui.QMessageBox.Save);
            value = message_box.exec_();

            if value == QtGui.QMessageBox.Save:
                response = self.save()
            elif value == QtGui.QMessageBox.Cancel:
                response = Warning('Action Cancelled')

        return response

    def get_recents(self):
        recent_dict = load_preferences(name='rst_recent_files')
        if recent_dict is None:
            recent_dict = {}
        return recent_dict.get('path_contexts', [])

    def add_to_recents(self, path_ctx):
        path_ctxs = self.get_recents()
        while path_ctx in path_ctxs:
            path_ctxs.remove(path_ctx)
        path_ctxs.insert(0, path_ctx)
        save_preferences('rst_recent_files', {'path_contexts':path_ctxs[:10]})
        # self._populate_recents_menu(path_ctxs[:10])

    def populate_recents_menu(self):
        path_ctxs = self.get_recents()
        self._populate_recents_menu(path_ctxs)

    # XXX TODO: Add recent menu when loading is possible
    # def _populate_recents_menu(self, path_ctxs):
    #     self.recent_menu.clear()
    #     for path_ctx in path_ctxs:
    #         name = path_ctx.get('name')
    #         pipe_ctx = PipeContext.from_path_context(path_ctx)
    #         label = '%s (%s)' % (name, pipe_ctx)
    #         callback = partial(self.open_, path_ctx=path_ctx)
    #         action = self.recent_menu.addAction(label, callback)

    # LIGHTNING ROOT
    def root(self, *args, **kwargs):
        return lightning.root(*args, **kwargs)

    def _build_file_menu(self, menubar):
        """
        _build_file_menu is an internal method of RSTDispatcher that  ...
        Builds the file menu, right now it is just exit.

        @param menubar: The existing top menu bar
        @type menubar: QMenuBar
        @returns: None
        @rtype:

        """
        file_menu = QtGui.QMenu('File')
        # This will take the new file browser to get the path context
        browser_action = file_menu.addAction('Open', self.open_browser)
        action = file_menu.addAction('Exit', self.close)
        #action.setIcon(ui_lib_old.ui_utils.get_icon('open'))
        menubar.addMenu(file_menu)
        self.file_menu = file_menu

    def warning(self, txt):
        """
        warning is a method of RSTDispatcher that ...
        Creates a new warning dialog and pops it up to the user with the
        given text

        @param txt: The message
        @type txt: string
        @returns: None
        @rtype:

        """
        warningbox = QtGui.QMessageBox()
        warningbox.setPalette(self.pal)
        warningbox.setText(txt)
        warningbox.setStandardButtons(QtGui.QMessageBox.Ok)
        warningbox.setDefaultButton(QtGui.QMessageBox.Ok)
        warningbox.exec_()

    def warning_yesorno(self, txt):
        """
        warning_yesorno is a method of RSTDispatcher that ...
        Creates a new warning dialog and pops it up to the user with the
        given text.  Then it gives the user the chance to cancel.

        @param txt: The message
        @type txt: string
        @returns: None
        @rtype:

        """
        msg_box = QtGui.QMessageBox()
        msg_box.setPalette(self.pal)
        msg_box.setText(txt)
        msg_box.setStandardButtons(
                        QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        msg_box.setDefaultButton(QtGui.QMessageBox.Yes)
        ret = msg_box.exec_()

        if ret == QtGui.QMessageBox.Yes:
            return 1
        else:
            return 0

    def submit_render(self):
        """
        submit_render is a method of RSTDispatcher that ...
        calls the submission after changing the cursor to busy

        @returns: None
        @rtype:

        """
        temp = self.cursor()
        self.setCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
        self.submission()
        self.setCursor(temp)

    def _read_farm_xml_cluster(self):
        context = PathContext(project=self.show_longname, disc=self.department)
        # Old pipeline read farm xml to get farm information
        # Switch this out to something else
        farm_xml = context.get_path('pr_config_dir')
        farm_xml += '/farm.xml'
        tree = cElementTree.parse(farm_xml)

        cluster_element = tree.find('clusters')
        render_cluster_element = cluster_element.find('prmanrender')
        render_cluster = render_cluster_element.get("cluster")
        render_priority = render_cluster_element.get("priority")

        process_cluster_element = cluster_element.find('process')
        process_cluster = process_cluster_element.get("cluster")
        process_priority = process_cluster_element.get("priority")

        for override in cluster_element.getiterator("processOverride"):
            if override.get("task") == 'ShotOpt':
                process_cluster = override.get('cluster')
                process_priority = override.get("priority")

        return {'process' : {'cluster': process_cluster,
                             'priority': process_priority},
                'render' : {'cluster' : render_cluster,
                            'priority': render_priority}
                }

    def prompt_to_save(self):
        if hou.ui.displayMessage("Save the current hip file?", buttons=("Yes", "No")) == 0:
            hou.hipFile.save()

    def prompt_update_cameras(self):
        # TODO Implement this
        cam_view = OutdatedCameraView()
        if cam_view.has_outdated_cameras():
            cam_view.exec_()


    def submission(self):
        """
        Create the submission object that will create the xml and the job
        to the farm.
        """
        # self.prompt_to_save()
        # self.prompt_update_cameras()
        # Get the information from the topform
        topform_info = self.toplayout.get_topform_info()
        resolution = topform_info['resolution']
        outformat = topform_info['output_format']
        after_job = topform_info['waitfor']
        #self.shotopt = self.toplayout.shot_opt_check.isChecked()
        table_info = self.get_table_info()
        self.wip_ctx = WipContext.from_path(
            str(self.toplayout.scene_render_edit.text())
        )
        submission = CmdDispatcher(self.wip_ctx, self.path_ctx, resolution,
                                          outformat, table_info, after_job=after_job,
                                          test_only = False, notes=str(self.note_edit.toPlainText()))
        job_ids = submission.submit()
        log_str = 'Submitted the following jobs:\n'
        for key, val in job_ids.iteritems():
            log_str = log_str + '{0} : {1}\n'.format(key, val)

        self.log_edit.append(log_str)
        ifd_log = '\n'.join(submission.ifd_paths)
        render_log = '\n'.join(submission.render_paths)
        path_log = '\n'.join(['The IFDs will be located here:',
                              ifd_log,
                              'The Images will be located here:',
                              render_log, '\n'])
        self.log_edit.append(path_log)

    def _write_layer_to_xml(self, layerdict):
        """
        _write_layer_to_xml is an internal method of RSTDispatcher that  ...
        creates an entry into an xml tree given the information pulled from
        a specific layer

        @param layerdict: the layer information in a dictionary
        @type layerdict: dictionary
        @returns: None
        @rtype:

        """
        my_pass = cElementTree.Element("")
        pass_node = self.passdict[layerdict['layer'] + "_" +
                                   layerdict['pass_type']]
        lightning.groups.root.pass_to_elem(my_pass, pass_node)
        lightning.groups.root.indent(my_pass)
        tmp = cElementTree.ElementTree(my_pass)
        tmp.write(layerdict['rlcxml'])

    def get_bottom_form_info(self):
        """
        get_bottom_form_info is a method of RSTDispatcher that ...
        has not been implemented yet.

        @returns: None
        @rtype:

        """
        tab_info = {}
        if self.bottomtab2:
            tab_count = self.bottomtab2.count()
            print 'Tab Count: ', tab_count
            for tab in range(tab_count):
                print 'Bottomtab Title: ', self.bottomtab2.tabText(tab)
                print 'Widget Text: ', self.bottomtab2.widget(tab).toPlainText()

    def get_table_info(self):
        """
        get_table_info is a method of RSTDispatcher that ...
        populates a list of dictionaries that contain the gui settings for
        each pass selected to render.

        @returns: all of the information contained in each layer
        @rtype: list of dictionaries

        """
        table_list = []
        model = self.table.model()
        for row in range(0, model.rowCount()):
            tmpdict = {}

            tmpdict['up'] = not self.table.indexWidget(model.index(row, 7)).isFlat()
            tmpdict['renderLeftEye'] = not self.table.indexWidget(model.index(row, 5)).isFlat()
            tmpdict['renderRightEye'] = not self.table.indexWidget(model.index(row, 6)).isFlat()

            if (not tmpdict['renderLeftEye']) and (not tmpdict['renderRightEye']) and (not tmpdict['up']):
                continue

            tmpdict['layer'] = str(self.table.itemFromIndex(model.index(row, 0)).text())
            tmpdict['pass_type'] = str(self.table.itemFromIndex(model.index(row, 1)).text())

            frame_range = str(self.table.indexWidget(model.index(row, 2)).text())
            tmpdict['original_frame_range'] = frame_range
            if frame_range == '':
                msg_box = QtGui.QMessageBox()
                msg_box.setPalette(self.pal)
                msg_box.setText("Warning, There was no frame range set for the " +
                               tmpdict['layer'] + " layer.\nSkipping it.")
                msg_box.setStandardButtons(QtGui.QMessageBox.Ok)
                msg_box.setDefaultButton(QtGui.QMessageBox.Ok)
                ret = msg_box.exec_()
                continue

            frame_range = frame_range.strip(' ')
            sections = frame_range.split(',')
            framerange = []
            for frames in sections:
                if 'x' in frames:
                    first_range = int(frames.split('-')[0])
                    last_range_x = frames.split('-')[1]
                    last_range = int(last_range_x.split('x')[0])
                    by_frame = int(last_range_x.split('x')[1])
                    frame_range = range(first_range, last_range + 1)
                    frame_range = frame_range[0:len(frame_range):by_frame]
                    [framerange.append(str(f)) for f in frame_range]

                elif '-' in frames:
                    first_range = frames.split('-')[0]
                    last_range = frames.split('-')[1]
                    framerange.append(first_range + "-" + last_range)

                else:
                    framerange.append(frames)

            tmpdict['frame_range'] = ",".join(framerange)
            tmpdict['up'] = not self.table.indexWidget(model.index(row, 7)).isFlat()
            tmpdict['camera'] = str(self.table.indexWidget(model.index(row, 8)).currentText())
            tmpdict['priority'] = str(self.table.indexWidget(model.index(row, 9)).displayText())
            tmpdict['cpus'] = str(self.table.indexWidget(model.index(row, 10)).displayText())
            tmpdict['mantra_cluster'] = str(self.table.indexWidget(model.index(row, 11)).displayText())

            table_list.append(tmpdict)

        return table_list

class DispatcherWipBrowser(RDialog):
    TITLE = 'File Browser'
    FRAME_BGC = QtGui.QPalette.Window
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('modal', True)
        kwargs.setdefault('width', 500)
        kwargs.setdefault('height', 600)
        super(DispatcherWipBrowser, self).__init__(*args, **kwargs)
        self.root = kwargs.get('root')
        if self.root is None:
            self.root = lightning.root()

        self.pipe_ctx = kwargs.get('pipe_ctx')
        if self.pipe_ctx is None:
            self.pipe_ctx = self.root.pipe_ctx.clone()

        self.path_ctx = None
        self.build()

    def build(self):
        scroll_area = QtGui.QScrollArea(parent=self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setBackgroundRole(QtGui.QPalette.Dark)

        self.contents_widget = QtGui.QWidget(parent=scroll_area)
        scroll_area.setWidget(self.contents_widget)

        self.main_layout = QtGui.QVBoxLayout(self.contents_widget)
        self.main_layout.addStretch(1)
        ctx_frame, ctx_input = RPipeContextInput.new_framed(
            value=self.pipe_ctx,
            parent=self.contents_widget,
            callback = self.update_wip_tree
        )
        ctx_frame.setBackgroundRole(self.FRAME_BGC)
        ctx_frame.setAutoFillBackground(True)
        self.pipe_ctx_input = ctx_input
        # Create the frame and browser for the WipBrowser
        self.frame, self.browser = RWipBrowser.new_framed(
            value=self.pipe_ctx,
            parent=self.contents_widget
        )
        self.frame.setBackgroundRole(self.FRAME_BGC)
        self.frame.setAutoFillBackground(True)

        self.update_wip_tree(self.pipe_ctx)

        # Accept/Cancel buttons
        #
        self.button_layout = QtGui.QHBoxLayout()

        self.accept_button = QtGui.QPushButton('Accept', self)
        self.button_layout.addWidget(self.accept_button)
        self.accept_button.clicked.connect(self.accept)

        self.cancel_button = QtGui.QPushButton('Cancel', self)
        self.button_layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self.reject)

        # layout controls
        #
        layout = QtGui.QVBoxLayout(self)
        layout.addWidget(scroll_area)
        layout.addLayout(self.button_layout)

    def update_wip_tree(self, pipe_ctx):
        self.browser.set_pipe_context(pipe_ctx)
        self.browser.update_tree()

    def get_name(self):
        return self.browser.get_selected()

    def get_pipe_ctx(self):
        return self.pipe_ctx_input.get_pipe_context()

    def accept(self):
        wip_ctx = self.browser.get_wip_context()
        if wip_ctx:
            self.wip_ctx = wip_ctx
            super(DispatcherWipBrowser, self).accept()
        else:
            popup.show_error('Invalid WIP',
                    'You mush specify a WIP', parent=self)

class Open_WipBrowser(DispatcherWipBrowser):
    TITLE = 'Open'

class DispatcherTopformLayout(QtGui.QGridLayout):
    """
    .. class:: DispatcherTopformLayout

        UI layout for all the Dispatcher options.

        .. data::
    """
    def __init__(self, palette=None, parent=None):
        super(DispatcherTopformLayout, self).__init__(parent)
        self.icondir = ui_lib_old.ui_utils.get_icon_directory()
        self.action_history = []
        self.sheet = ""
        if palette:
            self.pal = palette
            self.pal.setColor(QtGui.QPalette.Base, QtGui.QColor(220, 220, 220))
            self.pal.setColor(QtGui.QPalette.Text, QtGui.QColor("black"))
        # Don't think this needs to be after logic is split
        self.wip_ctx = get_pipe_context()
        self.show_longname = self.wip_ctx.project
        self.department = self.wip_ctx.discipline
        self.project_object = self.wip_ctx.get_project_obj()
        self.set_validations()
        self.init_ui()

    def get_topform_info(self):
        """
        get_topform_info is a method of RSTDispatcher that ...
        pulls all of the information from the top form and stores it in a
        dictionary.

        @returns: a dictionary of all the information in the top form
        @rtype: dictionary

        """
        topform_info = {}

        topform_info['render_scene'] = str(self.scene_render_edit.text())
        index = self.rescombo.currentIndex()
        entry = self.rescombo.itemData(index).toPyObject()[0]
        topform_info['resolution'] = Resolution(width=float(entry['renderWidth']),
                                                height=float(entry['renderHeight']))

        index = self.output_format_combo.currentIndex()
        format_info = self.output_format_combo.itemData(index).toPyObject()[0]
        topform_info['output_format'] = format_info

        topform_info['waitfor'] = int(self.qube_waitfor_edit.text())

        return topform_info

    def set_validations(self):
        """
        setValidations is a method of RSTDispatcher that ...
        This method sets up all appropriate validations for text fields.
        If a character is invalid, it will not be allowed in the text field.
        @returns: None
        @rtype:

        """

        #reg = QtCore.QRegExp("(\d+(\-\d*\,|\-\d+x\d*(\,|\, )))*")
        reg = QtCore.QRegExp("(\d+(,|\-\d+(,|x\d+,)))*")
        #105-110x2
        self.framerangevalidator = QtGui.QRegExpValidator(reg, self)

        reg = QtCore.QRegExp("\d+")
        self.digitvalidator = QtGui.QRegExpValidator(reg, self)

        reg = QtCore.QRegExp("\d{4}")
        self.digit4limitvalidator = QtGui.QRegExpValidator(reg, self)

        #to match between numbers 3000 to 5000
        #reg = QtCore.QRegExp("\b[3-5][0-9]{3}\b")

    def _clear_action_history(self):
        """
        _clear_action_history is an internal method of RSTDispatcher that  ...
        clears all history qactions in the qmenu to the right of the
        shot button.

        @returns: None
        @rtype:

        """
        for actiontup in self.action_history:
            if not actiontup[0] == self.actionsep:
                self.shot_qmenu.removeAction(actiontup[0])
        self.action_history = []
        self.action_history.append((self.actionsep, "sep"))

    def init_ui(self):
        iconsize = "/16x16/"
        lil_layout = QtGui.QHBoxLayout()
        # lil_layout.addWidget(self.shot_menu_button)

        # self.addWidget(self.shot_info_label, 0, 0)
        # self.addWidget(self.sequence_name, 0, 1)
        # self.addWidget(self.shot_name, 0, 2)
        self.addLayout(lil_layout, 0, 3)
        lil_layout.addItem(QtGui.QSpacerItem(150, 0))
        self.addItem(QtGui.QSpacerItem(250, 0), 0, 4)
        self.addItem(QtGui.QSpacerItem(250, 0), 0, 5)

        # RST Information
        self.rst_label = QtGui.QLabel("RST File:")
        self.rst_label.setAlignment(QtCore.Qt.AlignRight)
        self.rst_edit = QtGui.QLineEdit('')
        self.rst_edit.setReadOnly(True)
        self.rst_edit.setStyleSheet(self.sheet)

        # Wip Browser
        self.scene_render_label = QtGui.QLabel("Scene to Render:")
        self.scene_render_label.setAlignment(QtCore.Qt.AlignRight)
        self.scene_render_edit = QtGui.QLineEdit(self.wip_ctx.get_default_scene_path())
        self.scene_render_edit.setReadOnly(True)
        self.scene_render_edit.setStyleSheet(self.sheet)

        self.scene_render_button = QtGui.QPushButton(QtGui.QIcon(
                                self.icondir + iconsize +
                                 "green_arrow_down.png"), "")
        #disabled until needed
        self.scene_render_button.hide()
        self.scene_render_dialog_button = QtGui.QPushButton(QtGui.QIcon(
                                self.icondir + iconsize +
                                "computer_process.png"), "")
        self._scene_filedialog = QtGui.QFileDialog()
        self._scene_filedialog.setReadOnly(1)
        lil_layout2 = QtGui.QHBoxLayout()
        lil_layout2.addWidget(self.scene_render_button)
        lil_layout2.addWidget(self.scene_render_dialog_button)
        lil_layout2.addItem(QtGui.QSpacerItem(150, 0))
        self.addWidget(self.scene_render_label, 1, 0)
        self.addWidget(self.scene_render_edit, 1, 1, 1, 4)
        self.addLayout(lil_layout2, 1, 5)


        # self.rst_rsf_label = QtGui.QLabel("RLC RSF:")
        # self.rst_rsf_label.setAlignment(QtCore.Qt.AlignRight)
        # self.rst_rsf_edit = QtGui.QLineEdit("")
        # self.rst_rsf_edit.setStyleSheet(self.sheet)


        # self._rst_filedialog = QtGui.QFileDialog()
        # self._rst_filedialog.setReadOnly(1)
        # self.rlc_rst_button = QtGui.QPushButton(QtGui.QIcon(
        #                                     self.icondir + iconsize +
        #                                      "green_arrow_down.png"), "")
        # #disabled until needed
        # self.rlc_rst_button.hide()
        # self.rlc_rst_dialog_button = QtGui.QPushButton(QtGui.QIcon(
        #                                     self.icondir + iconsize +
        #                                      "computer_process.png"), "")
        lil_layout3 = QtGui.QHBoxLayout()
        # lil_layout3.addWidget(self.rlc_rst_button)
        # lil_layout3.addWidget(self.rlc_rst_dialog_button)
        lil_layout3.addItem(QtGui.QSpacerItem(150, 0))
        self.addWidget(self.rst_label, 2, 0)
        self.addWidget(self.rst_edit, 2, 1, 1, 4)
        self.addLayout(lil_layout3, 2, 5)


        self.resolution_label = QtGui.QLabel("Resolution:")
        self.resolution_label.setAlignment(QtCore.Qt.AlignRight)
        self.rescombo = QtGui.QComboBox()
        self.rescombo.setPalette(self.pal)
        self.addWidget(self.resolution_label, 3, 0)
        self.addWidget(self.rescombo, 3, 1)

        self.output_format_label = QtGui.QLabel("Output Format:")
        self.output_format_label.setAlignment(QtCore.Qt.AlignRight)
        self.output_format_combo = QtGui.QComboBox()
        self.output_format_combo.setPalette(self.pal)
        self.output_format_combo.addItem("exr", userData=("exr",))
        self.output_format_combo.addItem("jpg", userData=("jpg",))
        self.output_format_combo.addItem("sgi (8 bit)", userData=("sgi",))
        self.output_format_combo.addItem("sgi (16 bit)", userData=("sgi16",))
        self.output_format_combo.addItem("tga", userData=("tga",))
        self.output_format_combo.addItem("tif (8 bit)", userData=("tif",))
        self.output_format_combo.addItem("tif (16 bit)", userData=("tif16",))
        self.addWidget(self.output_format_label, 4, 0)
        self.addWidget(self.output_format_combo, 4, 1)

        self.qube_waitfor_label = QtGui.QLabel("Qube Waitfor ID:")
        self.qube_waitfor_label.setAlignment(QtCore.Qt.AlignRight)
        self.qube_waitfor_edit = QtGui.QLineEdit("0")
        self.qube_waitfor_edit.setStyleSheet(self.sheet)
        self.qube_waitfor_edit.setValidator(self.digitvalidator)
        self.addWidget(self.qube_waitfor_label, 5, 0)
        self.addWidget(self.qube_waitfor_edit, 5, 1)

        self.half_res_keys_label = QtGui.QLabel("Half Res Except Keys")
        self.half_res_keys_label.setAlignment(QtCore.Qt.AlignRight)
        self.half_res_keys_check = QtGui.QCheckBox()
        self.half_res_keys_check.setCheckState(True)
        self.half_res_keys_check.setStyleSheet(self.sheet)

        # Add the shot opt
        # self.shot_opt_label = QtGui.QLabel("Shot Opt")
        # self.shot_opt_label.setAlignment(QtCore.Qt.AlignRight)
        # self.shot_opt_check = QtGui.QCheckBox()
        # self.shot_opt_check.setCheckState(True)
        # self.shot_opt_check.setStyleSheet(self.sheet)
        # self.qube_waitfor_edit.setValidator(self.digitvalidator)
        self.addWidget(self.half_res_keys_label, 6, 0)
        self.addWidget(self.half_res_keys_check, 6, 1)

        # self.addWidget(self.shot_opt_label, 7, 0)
        #self.addWidget(self.shot_opt_check, 7, 1)

# ADD THIS IN LATER WHEN THINGS ARE WORKING
class DispatcherTable(QtGui.QTableWidget):
    def __init__(self, rows=0, columns=0, parent=None):
        super(DispatcherTable, self).__init__(rows, columns, parent)
        self.init_ui()

    def init_ui(self):
        #self.table = QtGui.QTableWidget(0, 13)
        self.signalmapper = QtCore.QSignalMapper(self)
        self.connect(self.signalmapper,
                     QtCore.SIGNAL("mapped(const QString &)"),
                     self._modify_link_list)

        # Change this so that it is expandable
        self.setHorizontalHeaderLabels(['Layer', 'Pass', 'Frame Range',
                                               'Link', 'Version\nPass', 'L', 'R',
                                                'Up', 'Camera', 'Priority',
                                                 'Procs', '', ''])

    def _modify_link_list(self, cellstring):
        """
        _modify_link_list is an internal method of RSTDispatcher that  ...
        is called by an action mapper.  The cellstring just identifies which
        layer and cell was modified, and then additionally modifies
        any cells linked with that one.  If the change is made in the bottom
        row, it affects all of the layers.

        @param cellstring: comma separated value row,column (bottom row has
                                                            its own entry)
        @type cellstring: string
        @returns: None
        @rtype:

        """
        splitter = cellstring.split(",")
        row = splitter[0]
        column = int(splitter[1])
        if row == "bottom":
            bottom = 0
            widget = self.bottom_row_table.cellWidget(bottom, column - 1)
            classname = widget.metaObject().className()
            info = ""
            if classname == "RToggleButton":
                info = widget.isFlat()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).flatten_or_not(info)
            elif classname == "MyLineEdit":
                info = widget.text()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setText(info)
            elif classname == "QComboBox":
                info = widget.currentIndex()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setCurrentIndex(info)
            elif classname == "QLineEdit":
                info = widget.text()
                for i in range(0, self.table.rowCount()):
                    self.table.cellWidget(i, column).setText(info)

        else:
            row = int(row)
            # if column == 11:
            #     widget = self.table.item(row, 0)
            #     widget2 = self.table.item(row, 1)
            #     self._view_images(widget.text(), widget2.text())
            if column == 12:
                widget = self.table.item(row, 0)
                if widget.text() in self.tab2list:
                    return
                index = self._add_new_render_setting("", widget.text())
                self.bottomtab.setCurrentIndex(1)
                self.bottomtab2.setCurrentIndex(index)
                self.tab2list.append(widget.text())
            elif column == 3:
                flat = self.table.cellWidget(row, column).isFlat()
                try:
                    self.linkedrowlist.remove(row)
                except:
                    pass
                if not flat:
                    self.linkedrowlist.append(row)

            else:
                if row in self.linkedrowlist:
                    widget = self.table.cellWidget(row, column)
                    classname = widget.metaObject().className()
                    info = ""
                    if classname == "RToggleButton":
                        info = widget.isFlat()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i,
                                                column).flatten_or_not(info)
                    elif classname == "MyLineEdit":
                        info = widget.text()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i, column).setText(info)
                    elif classname == "QComboBox":
                        info = widget.currentIndex()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i,
                                                column).setCurrentIndex(info)
                    elif classname == "QLineEdit":
                        info = widget.text()
                        for i in self.linkedrowlist:
                            self.table.cellWidget(i, column).setText(info)

class MyLineEdit(QtGui.QLineEdit):

    def __init__(self, string, parent=None):
        """
        __init__ is the constructor of the MyLineEdit class.
        This was customized to allow a line edit to have right click menu
        functionality

        @param string: the initial text for the line
        @type string: string
        @param parent:
        @type parent:
        @returns: n/a (constructor method)

        """
        QtGui.QLineEdit.__init__(self, string, parent)
        self.menu = None
        self.click_location=None

    def set_custom_context_menu(self, menu):
        """
        set_custom_context_menu is a method of MyLineEdit that ...

        @param menu: a menu to be tied to the right click functionality
        @type menu:
        @returns: None
        @rtype:

        """
        self.menu = menu

    def contextMenuEvent(self, event):
        """
        contextMenuEvent is a method of MyLineEdit that ...
        pops up the custom menu at the given even position

        @param event:
        @type event:
        @returns:
        @rtype:

        """
        self.click_location=event.pos()
        if self.menu == None:
            self.menu = QtGui.QMenu()
        self.menu.exec_(event.globalPos())

class MyTextEdit(QtGui.QTextEdit):

    def __init__(self, string, parent=None):
        """
        __init__ is the constructor of the MyTextEdit class.
        This was customized to allow a text edit to have right click menu
        functionality

        @param string:
        @type string:
        @param parent:
        @type parent:
        @returns: n/a (constructor method)

        """
        QtGui.QTextEdit.__init__(self, string, parent)
        self.menu = None

    def set_custom_context_menu(self, menu):
        """
        set_custom_context_menu is a method of MyTextEdit that ...

        @param menu:
        @type menu:
        @returns:
        @rtype:

        """
        self.menu = menu

    def contextMenuEvent(self, event):
        """
        contextMenuEvent is a method of MyTextEdit that ...

        @param event:
        @type event:
        @returns:
        @rtype:

        """
        if self.menu == None:
            self.menu = QtGui.QMenu()
        self.menu.exec_(event.globalPos())

class RToggleButton(QtGui.QPushButton):

    def __init__(self, icon, string, parent=None):
        """
        __init__ is the constructor of the RToggleButton class.
        This class was overridden to give push button disable functionality
        to the layer buttons

        @param icon: the path to the icon
        @type icon: string
        @param string: button text
        @type string: string
        @param parent:
        @type parent:
        @returns: n/a (constructor method)

        """
        self.parent = parent
        self.icon = None
        self.disabledicon = None

        if icon == "" or None:
            QtGui.QPushButton.__init__(self, string)
        else:
            self.icon = QtGui.QIcon(icon)
            QtGui.QPushButton.__init__(self, self.icon, string)
            size = QtCore.QSize(30, 30)

            self.setIconSize(size)
            self.disabledicon = QtGui.QIcon(self.icon.pixmap(self.iconSize()
                                                , mode=QtGui.QIcon.Disabled))

        self.setMinimumHeight(42)
        self.setMaximumWidth(42)
        self.setCheckable(0)
        self.connect(self, QtCore.SIGNAL('clicked()'), self._clickedd)

    def get_parent(self):
        """
        get_parent is a method of RToggleButton that ...
        returns the parent of the button to find out the row you're in.

        @returns:
        @rtype:

        """
        return self.parent

    def set_disabled_icon(self, icon):
        """
        set_disabled_icon is a method of RToggleButton that ...
        takes a string path and sets an icon to be the disabled icon for this
        button

        @param icon: path to the disabled icon
        @type icon: string
        @returns:
        @rtype:

        """
        self.disabledicon = QtGui.QIcon(icon)

    def set_normal_icon(self, icon):
        """
        set_normal_icon is a method of RToggleButton that ...
        defines the normal icon for the button

        @param icon:
        @type icon:
        @returns:
        @rtype:

        """
        self.icon == QtGui.QIcon(icon)
        self.setIcon(self.icon)

    def flatten_or_not(self, flatten):
        """
        flatten_or_not is a method of RToggleButton that ...
        pushes a button down entirely or not

        @param flatten:
        @type flatten: boolean
        @returns:
        @rtype:

        """
        if(flatten):
            self.setFlat(1)
            if self.disabledicon:
                self.setIcon(self.disabledicon)
        else:
            self.setFlat(0)
            if self.icon:
                self.setIcon(self.icon)

    def _clickedd(self):
        """
        _clickedd is an internal method of RToggleButton that  ...
        redefines the click behavior of the button

        @returns:
        @rtype:

        """
        if(self.isFlat()):
            self.flatten_or_not(0)
        else:
            self.flatten_or_not(1)

class GenericThread(QtCore.QThread):
    def __init__(self, function, *args, **kwargs):
        QtCore.QThread.__init__(self)
        self.function = function
        self.args = args
        self.kwargs = kwargs

    def __del__(self):
        self.wait()

    def run(self):
        self.function(*self.args,**self.kwargs)
        return


def main():
    print 'Starting the RST Dispatcher...'
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = None

    x = Dispatcher()
    x.start()

if __name__ == '__main__':
   main()

