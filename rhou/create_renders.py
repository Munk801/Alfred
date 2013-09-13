#!/usr/bin/env python

#Built-In
import re
import os
import sys

#Houdini
import hou

#ReelFX
from houdini_tools.hda_modules.rfxAbcCamera import rfxAbcCamera
import lightning
from lightning.rhou import render
from pipe_utils import xml_utils
from pipe_utils.sequence import FrameRange, FrameSet

from pipe_utils.string_utils import str_to_obj

def get_layer_names(layer_info):
    """ Retrieve the layer names from the layer xml. """
    layer_names = []
    for layer in layer_info:
        layer_names.append(layer.get('layer'))
    return layer_names

def get_channel_cams(camera_node):
    """ Get the stereo channel camera from the stereo cam."""
    children = camera_node.children()
    child_cams = [cam for cam in children if cam.type().name() == 'cam']
    left_cam, right_cam = None, None
    for child_cam in child_cams:
        if child_cam.name() == 'left_camera':
            left_cam = child_cam
        if child_cam.name() == 'right_camera':
            right_cam = child_cam
    return left_cam, right_cam

# XXX TODO Currently the way that the houdini scripts get run
# is different so the startup arguments will not work correctly.
# However, this current method is not the best way to do it as
# the environment variable can get rather large to pass through
def get_environment_args():
    args_env =  os.environ['PY_STARTUP_ARGS']
    argv = str_to_obj(args_env, useb64decode=True)
    return argv

def symlink_files_to_renders(items_to_symlink, symlink_locations):
    for symlink_item in items_to_symlink:
        for location in symlink_locations:
            base_filename = os.path.basename(symlink_item)
            try:
                os.symlink(symlink_item, os.path.join(location, base_filename))
            except OSError:
                # File exists so we do not need to worry
                continue

def main():
    argv = get_environment_args()

    # Get all the argument values out
    path_ctx = argv['path_ctx']
    xml_path = argv['xml_path']
    image_paths = argv['image_paths']
    ifd_paths = argv['ifd_paths']
    render_scene = argv['render_scene']
    layer_info = argv['layer_info']

    hou_root = hou.node('/')
    # Grab the passes from the xml
    render_prefs = xml_utils.ElementTree.parse(xml_path)
    render_root = render_prefs.getroot()
    # Get the render passes
    renders = render_root.find('renders')
    layer_info = renders.getchildren()
    # Get the resolution
    res_element = render_root.find('resolution')
    resolution = (res_element.get('width'), res_element.get('height'))
    # Get the rst root node
    response = lightning.groups.root.Root.from_path_context(path_ctx)
    root = response.payload
    # Get the different passes
    layer_names = get_layer_names(layer_info)
    # Retrieve the mantra nodes that are created
    mantra_nodes = render.render(root, passes=layer_names, to_render = False)
    # Set the frame ranges and cameras for all the nodes
    # XXX DONT KNOW IF THE LIST IS 1:1 TO LAYER LIST
    for i, mantra_node in enumerate(mantra_nodes):
        # Connect the rfxQube node to this
        rfx_qube_node = mantra_node.createOutputNode('rfxQube')

        hou_children = hou_root.allSubChildren()
        # get the camera
        camera_name = layer_info[i].get('camera')
        camera_node = [c for c in hou_children if c.name() == camera_name]
        if camera_node:
            camera_node = camera_node[0]
        # If a specific eye was specified, select that
        # Set the take
        hou.hscript('takeset {0}'.format(mantra_node.name()))
        # Set the camera resolution
        # XXX TODO: WHAT HAPPENS IF THERE ARE NO CAMERAS
        camera_dict = {
            'resolution_menu' : 'custom_res',
            'custom_resx' : resolution[0],
            'custom_resy' : resolution[1],
        }
        render.set_parms_in_take(camera_dict, camera_node)
        left_cam, right_cam = get_channel_cams(camera_node)
        # Set the camera and frame_range
        # Check whether the user specified only one channel
        left_channel = eval(layer_info[i].get('left'))
        right_channel = eval(layer_info[i].get('right'))
        render_cam = None
        # Default to the camera set if there are no channels
        if left_channel and not right_channel:
            render_cam = left_cam
        if right_channel and not left_channel:
            render_cam = right_cam
        if not render_cam:
            render_cam = camera_node
        frame_set = FrameSet.parse(layer_info[i].get('range'))
        # for frame_range in frame_set.ranges:
        print "Camera Path: {0}".format(render_cam.path())
        parm_dict = {
            'camera' : render_cam.path(),
            # 'trange' : 'on',
            # 'f1'     : frame_range.start,
            # 'f2'     : frame_range.end,
        }
        render.set_parms_in_take(parm_dict, mantra_node)
        # Override the frame range in the rfxQube
        render.set_parms_in_take({'overrideTrange' : True}, rfx_qube_node)
        render.set_parms_in_take({'use_arbitrary_frames' : True}, rfx_qube_node)
        render.set_parms_in_take({'arbitrary_frames' : str(frame_set)}, rfx_qube_node)

        # include all parms in the take
        hou.hscript('takeinclude {0} *'.format(render_cam.path()))

        # Set the IFD path and image path
        image_dict = {
            'vm_picture' : image_paths[i],
            'soho_outputmode' : True,
            'soho_diskfile' : ifd_paths[i]
        }
        render.set_parms_in_take(image_dict, mantra_node)

        # Create the directory if they do not exist
        if not os.path.exists(os.path.dirname(image_paths[i])):
            os.makedirs(os.path.dirname(image_paths[i]))
        if not os.path.exists(os.path.dirname(ifd_paths[i])):
            os.makedirs(os.path.dirname(ifd_paths[i]))

        # mantra_node.render()
        render.set_parms_in_take({'show_confirmation' : 0}, rfx_qube_node)
        rfx_qube_node.parm('execute2').pressButton()

        # Create the symlink
        items_to_symlink = [render_scene, xml_path]
        symlink_locations = [os.path.dirname(image_paths[i]),
                             os.path.dirname(ifd_paths[i])]
        symlink_files_to_renders(items_to_symlink, symlink_locations)

    # Save houdini scene
    hou.hipFile.save(render_scene)

    # Secure shutdown


if __name__ == '__main__':
    main()
