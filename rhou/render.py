#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#
# Third party
import hou

# Custom
import lightning
from houdini_tools.hda_modules.rfxAsset import rfxAsset
from houdini_tools.hda_modules.rfxAbcCamera import rfxAbcCamera
from houdini_tools import look_utils


#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#
#Mantra Parms
MANTRA_HRST_ATTRIBUTE_MAP = {
    'vm_usecacheratio'       :  {'Fixed Size':0, 'Proportion of Physical Memory':1},
    'soho_spoolrenderoutput' :  {"Don't capture render output":0, 'Capture render output for graphical apps':1, 'Capture render output for all apps':2},
    'vm_vexprofile'          :  {'No VEX Profiling':0, 'Execution profiling':1, 'Profiling and NAN detection':2}
    }

MANTRA_SPECIAL_SETTINGS = ['shutter']

OBJECT_MODE_MAP = {
    'visible' : 'forceobject',
    'matte'   : 'matte_objects',
    'phantom' : 'phantom_objects',
    'exclude' : 'excludeobject'
    }

AOVS_PARM_MAP = {
    'diffuseColor'   : {'vm_variable_plane':'direct_reflectivity', 'vm_lightexport':0},
    'depth'          : {'vm_variable_plane':'Pz', 'vm_lightexport':0, 'vm_vextype_plane':'float'},
    'normals'        : {'vm_variable_plane':'N', 'vm_lightexport':0},
    'pointWorld'     : {'vm_variable_plane':'P', 'vm_lightexport':0},
    'subsurface'     : {'vm_variable_plane':'sss_multi'},
    'direct_emission': {'vm_sfilter_plane':'fullopacity'},
    'direct_comp'    : {'vm_channel_plane': 'direct', 'vm_componentexport':1},
    'indirect_comp'  : {'vm_channel_plane': 'indirect', 'vm_componentexport':1}
    }


#Object Parms
OBJECT_HRST_ATTRIBUTE_MAP = {
    'motionBlur'  : 'geo_velocityblur',
    'matteShade'  : 'vm_matte',
    }

OBJECT_SPECIAL_SETTINGS = ['castShadows', 'visibleInReflections', 'visibleInRefractions', 'visibleToIndirectRays', 'matte_aovs', 'cropMask']


#Light parms
LIGHT_HRST_ATTRIBUTE_MAP = {
    'shadow_type' : {'off':0, 'raytrace':1, 'depthmap':2}
    }

LIGHT_CONTRIBUTION_ATTRIBUTE_MAP = {
    'contributeToVolume'       : 'volume',
    'contributeToDiffuse'      : 'diffuse',
    'contributeToRefract'      : 'refract',
    'contributeToCoat'         : 'coat',
    'contributeToReflect'      : 'reflect',
    'contributeToAnyDiffuse'   : 'diffuse|volume',
    'contributeToAnyNonDiffuse': '-diffuse & -volume'
    }


#Others
TMP_OBJ_SUBNET_PATH = '/obj/tmp_render_objs'
TMP_SHADOW_MATTE_NAME = 'tmp_render_shadow_matte'

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- CLASSES --#
class Mantra(object):
    """
    The Mantra object which stores all the render settings from HRST.
    """
    def __init__(self, layer):
        self.layer = layer
        self.name = layer['name']
        self.pass_type = layer.pass_type
        self.mantra_settings = self.get_mantra_settings()
        self.planes = self.get_planes(layer)

        self.objects = self.get_render_items()
        self.lights = self.get_render_items(item_type = 'light')
        special_objects = self._get_special_objects()
        self.no_shadow_objects = special_objects['no_shadow_objects']
        self.no_reflection_objects = special_objects['no_reflection_objects']
        self.no_refraction_objects = special_objects['no_refraction_objects']
        self.no_mask_objs = special_objects['no_mask_objs']
        self.camera = self.get_camera()


    def get_source_groups(self):
        """
        Get HRST source groups
        """
        return self.layer.find(type='SourceInstance')


    def get_mantra_settings(self):
        """
        Get Mantra ROP settings from HRST.
        """
        settings = {}

        #Get the settings from HRST
        for attributeGroup in self.layer['pass_settings']:

            #We do special case for AOVs, and we don't like attributes in Submission
            if attributeGroup.name == 'AOVs' or attributeGroup.name == 'Submission':
                continue

            for attribute in attributeGroup.get_attributes():
                #Houdini treats some long string menu parms as int menu parms.
                #We have to do a mapping here.
                value = attribute.value
                #Remapping some attribute values
                if attribute.name in MANTRA_HRST_ATTRIBUTE_MAP:
                    value = MANTRA_HRST_ATTRIBUTE_MAP[attribute.name][attribute.value]
                settings[attribute.name] = value

        return settings


    def get_planes(self, layer):
        """
        Get extra render planes list
        """
        aovs = []

        #Get the aovs from HRST
        for attributeGroup in self.layer['pass_settings']:

            #Get wanted AOVs
            if attributeGroup.name == 'AOVs':
                for attribute in attributeGroup.get_attributes():
                    value = attribute.value
                    if value:
                        aovs.append(attribute.name)

        return aovs


    def get_render_items(self, item_type = 'geom'):
        """
        Get all the objects that will be rendered.
        """
        render_objects = []
        source_groups = self.get_source_groups()
        for group in source_groups:
            if group.source_type == item_type:
                render_objects.extend( self._get_render_items_from_source_group(group) )

        return render_objects


    def _get_render_items_from_source_group(self, group):
        """
        Get render objects/lights (RenderObject) from a HRST source group.
        """
        if group.source_type == 'geom':
            return [RenderObject(group, HRST_obj) for HRST_obj in group['members']]
        else:
            return [RenderItem(group, HRST_obj) for HRST_obj in group['members']]


    def _get_special_objects(self):
        """
        Get lists of special setting objects.
        """
        return_dict = {}
        no_shadow_objects = []
        no_reflection_objects = []
        no_refraction_objects = []
        no_mask_objs = []
        for obj in self.objects:
            if obj.no_shadow:
                no_shadow_objects.append(obj)
            if obj.no_reflection:
                no_reflection_objects.append(obj)
            if obj.no_refraction:
                no_refraction_objects.append(obj)
            if obj.no_cropmask:
                no_mask_objs.append(obj)

        return_dict['no_shadow_objects'] = no_shadow_objects
        return_dict['no_reflection_objects'] = no_reflection_objects
        return_dict['no_refraction_objects'] = no_refraction_objects
        return_dict['no_mask_objs'] = no_mask_objs

        return return_dict


    def get_rendered_magic_aovs(self):
        """
        Get all the magic AOVs that are going to be rendered.
        """
        aovs = []
        magic_aovs = None
        for obj in self.objects:
            #TODO Multi rfxAssets
            a_rfxAsset = rfxAsset.find(hou.node(obj.HRST_path))
            if a_rfxAsset:
                magic_aovs = a_rfxAsset.get_magic_aovs()

            if magic_aovs:
                for magic_aov in magic_aovs:
                    if magic_aov.aov_name not in [aov.aov_name for aov in aovs]:
                        aovs.append(magic_aov)

        return aovs


    def get_camera(self):
        """
        Get camera on the scene or from HRST.
        """
        rfxcam = None
        cam = None

        #Get camera from current view port.
        if hou.isUIAvailable():
            d = hou.ui.curDesktop()
            viewport = d.paneTabOfType(hou.paneTabType.SceneViewer).curViewport()
            cam = viewport.camera()

        if not cam:
            #Get the first rfxcam
            for abcCam in rfxAbcCamera.find_all():
                cam = abcCam
                break

        if cam and cam.parent() and rfxAbcCamera.is_rfx_abc_camera(cam.parent()):
            cam = cam.parent()

        if not cam:
            #Get any camera from the scene.
            cam = [c for c in hou.node('/').allSubChildren() if c.type().name() == 'cam']
            if cam:
                cam = cam[0]

        #If there is no camera in the scene, Create one from current posititon.
        if not cam:
            cam = hou.node('/obj').createNode('cam', 'cam1')

        if isinstance(cam, str):
            cam = hou.node(cam)

        return cam


class RenderItem(object):
    """
    Items that specified in HRST.
    """
    def __init__(self, group, HRST_obj):
        self.group = group
        self.name = group.get_name()
        self.object_type = group.source_type

        self.HRST_obj = HRST_obj
        self.HRST_path = self.get_HRST_path()
        self.obj_path = self.get_obj_path()
        self.settings = self._get_group_settings()


    def get_HRST_path(self):
        return self.HRST_obj


    def get_obj_path(self):
        return self.HRST_obj


    def _get_group_settings(self):
        """
        Get the settings from HRST a source group.
        """
        attribute_overrides = {}

        #Get source setting groups list
        attributes = self.group.get_attribute('source_settings')
        for attribute in attributes.get_attributes():
            #This is the group render mode
            if isinstance(attribute, lightning.attributes.Enum):
                continue

            for attribute_item in attribute:
                if not attribute_item.locked:
                    #Remapping the parm name
                    if attribute_item.name in OBJECT_HRST_ATTRIBUTE_MAP:
                        parm_name = OBJECT_HRST_ATTRIBUTE_MAP[attribute_item.name]
                    else:
                        parm_name = attribute_item.name

                    attribute_overrides[parm_name] = attribute_item.value

        #Get material AOVs.
        aov_list = self.group.get_attribute('aovs')
        if aov_list.count():
            attribute_overrides['matte_aovs'] = aov_list

        return attribute_overrides



class RenderObject(RenderItem):
    """
    Objects that specified in HRST.
    """
    def __init__(self, group, HRST_obj):
        RenderItem.__init__(self, group, HRST_obj)
        self.render_mode = self.get_render_mode()
        self.merge_SOP_name = self.name
        self.obj_path = self.get_obj_path()

        self.rfxAssets = self.get_rfxAssets()
        self.prim_group = self.get_prim_group()
        self.no_shadow = False
        self.no_reflection = False
        self.no_refraction = False
        self.no_cropmask = False
        self.set_special_settings()



    def get_render_mode(self):
        attributes = self.group.get_attribute('source_settings')
        mode = None
        if attributes:
            smode = attributes.get('mode')
            if smode:
                mode = smode.value

        return OBJECT_MODE_MAP[mode] if mode and mode in OBJECT_MODE_MAP.keys() else None


    def get_prim_group(self):
        grp = ''
        if ':' in self.HRST_obj:
            grp = self.HRST_obj.split(':')[-1].replace('/','_')

        if grp.endswith('_GRP'):
            grp = '{0}*'.format(grp)

        return grp


    def get_HRST_path(self):
        return self.HRST_obj.split(':')[0]


    def get_obj_path(self):
        return self._get_tmp_OBJ_path() if ':' in self.HRST_obj else self.HRST_path


    def _get_tmp_OBJ_path(self):
        """
        Get temp object_merge OBJ path. (render with prim groups)
        """
        OBJ_name = self._get_tmp_OBJ_name()
        return '{0}/{1}'.format(TMP_OBJ_SUBNET_PATH, OBJ_name)


    def _get_tmp_OBJ_name(self):
        """
        Naming temp object_merge SOP.
        """
        OBJ_name = '{0}_{1}'.format(self.name,self.HRST_path.replace('/','_'))

        #OBJ_name = self.name
        self.merge_SOP_name = OBJ_name
        return OBJ_name


    def get_rfxAssets(self):
        """
        Get the real rfxAsset.
        #This function trace back to the referenced rhxAsset SOP
        #if it finds a object merge SOP.
        """
        rfxAssets = []
        for a_rfxAsset in rfxAsset.find_all(hou.node(self.HRST_path)):
            rfxAssets.append(a_rfxAsset)

        return rfxAssets if rfxAssets else []


    def set_special_settings(self):
        """
        Get lists of special setting objects.
        """
        for setting in self.settings:
            if not self.settings[setting]:
                if setting == 'castShadows':
                   self.no_shadow = True
                if setting == 'visibleInReflections':
                   self.no_reflection = True
                if setting == 'visibleInRefractions':
                   self.no_refraction = True
                if setting == 'cropMask':
                   self.no_cropmask = True


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- Functions --#
def render(root, passes = [], to_render = True):
    """
    Create Mantra ROPs and apply settings
    """
    selected_nodes = hou.selectedNodes()
    clean_tmp_geoms()
    #Get takes in Main.
    take_list = hou.hscript('takels -i -q -p Main')[0].split('\n')[:-1]

    layers = root.find(type='Pass')
    mantras = []
    #Create and setting Mantras
    for layer in layers:
        #Only render selected passes when user specified.
        if passes and layer['name'] not in passes:
            continue

        # Make sure we are doing everyting starts with Main take
        hou.hscript('takeset Main')

        #For each pass we create a Mantra ROP for it.
        mantra = Mantra(layer)
        #Move the node posititon
        mantra_ROP = create_Mantra_ROP(mantra, pos = (0, layers.index(layer)*-1))

        #Create all the temp objs we need for this render
        create_tmp_geoms(mantra)

        #Set mantra parms
        apply_mantra_settings(mantra, mantra_ROP)

        #Add render objects to Mantra
        set_parms_in_take({'vobject':''}, node = mantra_ROP)
        for render_mode in OBJECT_MODE_MAP:
            set_render_objects(mantra, mantra_ROP, OBJECT_MODE_MAP[render_mode])

        #Add render lights to Mantra
        set_parms_in_take({'alights':''}, node = mantra_ROP)
        forcelights = ''
        for light in mantra.lights:
            forcelights = '{0} {1} '.format(light.obj_path, forcelights)
        set_parms_in_take({'forcelights':forcelights}, node = mantra_ROP)
        
        
        
        #Create a NEW take from Main for each Mantra ROP
        hou.hscript('takeautomode off')
        if mantra.name in take_list:
            hou.hscript('takerm {0} -R'.format(mantra.name))
        hou.hscript('takeadd -c -p Main {0}'.format(mantra.name))

        #Set camera shutter speed
        if mantra.mantra_settings.has_key('shutter') and mantra.mantra_settings['shutter']:
            set_parms_in_take({'shutter':mantra.mantra_settings['shutter']}, node = mantra.camera)

        #Set camera crop
        cropmask = '* '
        cropmask += list_to_string(mantra.no_mask_objs, exclude=True)
        set_parms_in_take({'cropmask':cropmask}, node=mantra.camera)

        #RFXcamera does something magic and set the translate parms when rendering.
        #Allow those parms being modified in the take.
        if rfxAbcCamera.is_rfx_abc_camera(mantra.camera):
            hou.hscript('takeinclude {0} *'.format(mantra.camera.path()))

        #Set object parms
        apply_object_settings(mantra)

        #We need to get magic_aovs for future use, also magic_aoves must be queried in take
        #We don't need it anymore since we have that handled in SOHO
        #magic_aovs = mantra.get_rendered_magic_aovs()

        #Set light parms
        apply_light_settings(mantra)

        hou.hscript('takeset Main')
        hou.hscript('takeautomode off')
        
        
        
        #Set the magic shader image planes after setting objests. Must do
        #This has been handled in SOHO
        #set_magic_shader_planes(mantra, magic_aovs)

        #Set render take for this pass in Main
        mantra_ROP.parm('take').set(mantra.name)
        mantras.append(mantra_ROP)

    #Set back to Main take
    hou.hscript('takeset Main')

    #Set back User selected nodes
    try:
        for node in selected_nodes:
            node.setSelected(True)
    except:
        pass

    if to_render:
        for mantra_ROP in mantras:
            mantra_ROP.render()

    return mantras


def create_Mantra_ROP(mantra, pos = None):
    """
    Create a Mantra ROP in Houdini.
    """
    mantra_ROP = hou.node('/out/{0}'.format(mantra.name))
    if not mantra_ROP:
        mantra_ROP = hou.node('/out/').createNode('ifd', '{0}'.format(mantra.name))
        if pos:
            mantra_ROP.move(pos)

    return mantra_ROP


def apply_mantra_settings(mantra, mantra_ROP):
    """
    Apply Mantra settings
    """
    for setting in mantra.mantra_settings:
        if not setting in MANTRA_SPECIAL_SETTINGS:
            set_parms_in_take({setting:mantra.mantra_settings[setting]}, node = mantra_ROP)

    set_planes(mantra)
    mantra_ROP.parm('camera').set(mantra.camera.node('left_camera').path() if rfxAbcCamera.is_rfx_abc_camera(mantra.camera) else mantra.camera.path())


def set_render_objects(mantra, mantra_ROP, render_mode):
    """
    Set render objects.
    render_mode = forceobject, matte_objects, phantom_objects, excludeobject
    """
    objects = ''

    for obj in mantra.objects:
        if obj.render_mode == render_mode and obj.obj_path not in objects.split():
            objects = '{0}{1} '.format(objects, obj.obj_path)

    set_parms_in_take({render_mode:objects}, node = mantra_ROP)


def apply_object_settings(mantra):
    """
    Apply HRST object settings to Mantra
    """
    for obj in mantra.objects:
        objNode = hou.node(obj.obj_path)
        if objNode:
            for setting in obj.settings:
                #Regular set parms
                if setting not in OBJECT_SPECIAL_SETTINGS:
                    set_parms_in_take({setting:obj.settings[setting]}, node = objNode)

                #Magic AOV set parms, Bty pass only
                elif setting == 'matte_aovs' and obj.rfxAssets:
                    for a_rfxAsset in obj.rfxAssets:
                        render_aovs = [aov for aov in a_rfxAsset.get_imported_magic_aovs() if aov.aov_name in obj.settings[setting]]
                        _set_magic_aovs_in_take(a_rfxAsset, render_aovs)

        #Set global OBJ settings
        #Reflection set parms
        if objNode and mantra.no_reflection_objects:
            no_reflection = '* '
            no_reflection += list_to_string(mantra.no_reflection_objects, exclude = True)
            set_parms_in_take({'reflectmask':no_reflection}, node = objNode)

        #Refraction set parms
        if objNode and mantra.no_refraction_objects:
            no_refraction = '* '
            no_refraction += list_to_string(mantra.no_refraction_objects, exclude = True)
            set_parms_in_take({'refractmask':no_refraction}, node = objNode)

        #Do shadow pass
        if objNode and mantra.pass_type == 'shadow':
            #Create shadow map shader for render
            shadow_matte_SHOP = hou.node('/shop/{0}'.format(TMP_SHADOW_MATTE_NAME))
            if not shadow_matte_SHOP or not shadow_matte_SHOP.type().name() == 'v_shadowmatte':
                shadow_matte_SHOP = hou.node('/shop/').createNode('v_shadowmatte', TMP_SHADOW_MATTE_NAME)
            #Set shadow matte shader to all the visible object.
            if obj.render_mode == 'forceobject':
                #Regular objects
                set_parms_in_take({'shop_materialpath':shadow_matte_SHOP.path()}, node = objNode)

                #RFX Objects.
                #We have to turn off look in rfxAsset SOP in order to show the shadow map.
                for a_rfxAsset in obj.rfxAssets:
                    set_parms_in_take({'import_look':False}, a_rfxAsset.sesi_node)

        #Do matte pass
        elif objNode and mantra.pass_type == 'matte':
            #Find the rfxAsset SOP and get Magic Aovs.
            if not obj.obj_path == obj.HRST_path:
                render_node = objNode.renderNode()
                numobj = render_node.parm('numobj').eval()

                for num in range(1, numobj+1):
                    obj_path = render_node.parm('objpath{0}'.format(num)).eval()
                    if obj_path == obj.HRST_path:
                        #For each HRST objects, we need to put all the geometry parts in one channel.
                        #We name the AOV for each object all same here.
                        for a_rfxAsset in obj.rfxAssets:
                            groups = render_node.parm('group{0}'.format(num)).eval()
                            magic_aov = look_utils.MagicAov(groups, obj.name)
                            _set_magic_aovs_in_take(a_rfxAsset, [magic_aov])
                            #The magic matte should be always * when render with matte pass
                            a_rfxAsset.set_magic_matte_shader('*')
                        break

            else:
                for a_rfxAsset in obj.rfxAssets:
                    magic_aov = look_utils.MagicAov('*', obj.name)
                    _set_magic_aovs_in_take(a_rfxAsset, [magic_aov])
                    #The magic matte should be always * when render with matte pass
                    a_rfxAsset.set_magic_matte_shader('*')

        #Do ambient occlusion pass
        elif objNode and mantra.pass_type == 'ambientOcclusion':
            HRST_Node = hou.node(obj.HRST_path)

            render_node = HRST_Node.renderNode()
            if render_node.name() == "AO_ATTR":
                render_node = render_node.inputs()[0]

            if render_node.geometry() and 'shop_materialpath' not in [attr.name() for attr in render_node.geometry().primAttribs()]:
                return

            #Create a Attribute Node so it can hook with rfx SOHO code
            attri_AO_SOP = HRST_Node.node("AO_ATTR")
            if not attri_AO_SOP:
                attri_AO_SOP = HRST_Node.createNode("attribcreate::2.0", "AO_ATTR")

            attri_AO_SOP.setInput(0, render_node)

            #This is the way we add render flag in a take
            if not attri_AO_SOP.isRenderFlagSet():
                hou.hscript('takeinclude -r {0}'.format(attri_AO_SOP.path()))
                hou.hscript('takeinclude -r {0}'.format(render_node.path()))
                attri_AO_SOP.setRenderFlag(True)

            attri_AO_SOP_settings = {'numattr' : 1,
                                     'name1'   : 'shop_materialpath',
                                     'class1'  : 1,
                                     'type1'   : 3,
                                     'string1' : '`ifs(hasprimattrib("{0}", "shop_materialpath"), prims("{0}", $PR, "shop_materialpath")/__OCCLUSION__, "")`'.format(render_node.path())
            }

            set_parms_in_take(attri_AO_SOP_settings, attri_AO_SOP)
            attri_AO_SOP.hide(True)


def apply_light_settings(mantra):
    """
    Apply HRST light settings to Mantra
    """
    for light in mantra.lights:
        lightNode = hou.node(light.obj_path)
        if lightNode:
            contributions = []
            for setting in light.settings:
                if setting in LIGHT_CONTRIBUTION_ATTRIBUTE_MAP:
                    contributions.append(setting)
                else:
                    #Regular attribute set parms
                    set_parms_in_take({setting:LIGHT_HRST_ATTRIBUTE_MAP[setting][light.settings[setting]]}, node = lightNode)

            #Light contirbute set parms
            if contributions:
                contrib_dict = {}
                set_parms_in_take({'light_contrib':len(contributions)}, lightNode)
                for index, contribution in enumerate(contributions):
                    index = index + 1
                    contrib_dict['light_contribenable{0}'.format(index)] = light.settings[setting]
                    contrib_dict['light_contribname{0}'.format(index)] = LIGHT_CONTRIBUTION_ATTRIBUTE_MAP[contribution]
                set_parms_in_take(contrib_dict, node = lightNode)

            #Shadow casting set parm
            if mantra.no_shadow_objects:
                no_shadow = '* '
                no_shadow += list_to_string(mantra.no_shadow_objects, exclude = True)
                set_parms_in_take({'shadowmask':no_shadow}, node = lightNode)

            #Set light export prefix
            prefix_parm = lightNode.parm('vm_export_prefix')
            try:
                if prefix_parm:
                    set_parms_in_take({'vm_export_prefix':'{0}_'.format(light.name)},lightNode)

                else:
                    folder = hou.FolderParmTemplate('folder', 'HRST Settings')
                    folder.addParmTemplate(hou.StringParmTemplate('vm_export_prefix', 'Light Export Prefix', 1, ('{0}_'.format(light.name),)))
                    parm_group = lightNode.parmTemplateGroup()
                    parm_group.append(folder)
                    lightNode.setParmTemplateGroup(parm_group)
            except hou.OperationFailed:
                print('Failed to set light group name <{0}> as AOV prefix, Use light name instead.'.format(light.name))


def set_planes(mantra):
    """
    Set image planes in the mantra node.
    """
    mantra_ROP = hou.node('/out/{0}'.format(mantra.name))
    if not mantra.planes:
        return

    if not mantra_ROP:
        print "No mantra ROP found. Unable to set AOVs"
        return

    plane_types = {'direct':{'name':[],'comp':[],'skip':False, 'emission':False},
                   'indirect':{'name':[],'comp':[],'skip':False, 'emission':False},
                   'others':[]
                   }
    allowed_comps = ['Diffuse', 'Reflect', 'Coat', 'Refract', 'Volume']

    comps = []
    h_planes = []
    #Catalog them
    for plane in mantra.planes:
        if plane.startswith('direct') or plane.startswith('indirect'):
            for p_type in ['direct', 'indirect']:
                plane_types[p_type]['name'].append(plane)
                comp = plane.split(p_type )[-1]
                if comp == 'Combined':
                    plane_types[p_type]['skip'] = True

                if not comp == 'Emission':
                    plane_types[p_type]['comp'].append(comp)
                else:
                    plane_types[p_type]['emission'] = True
        else:
            plane_types['others'].append(plane)

    #Create houdini usable plane list
    for p_type in ['direct', 'indirect']:
        if plane_types[p_type]['skip']:
            plane_types[p_type]['comp'] = []
            h_planes.append(p_type)
        else:
            h_planes.append('{0}_comp'.format(p_type))

        if plane_types[p_type]['emission']:
            h_planes.append('{0}_emission'.format(p_type))

    h_planes.extend(plane_types['others'])


    #Eye AOVs
    #Find the rfxAsset SOP and get Magic Aovs.
    for obj in mantra.objects:
        if obj.render_mode == 'forceobject' and obj.rfxAssets:
            for a_rfxAsset in obj.rfxAssets:
                objNode = hou.node(obj.obj_path)
                imported_aovs = a_rfxAsset.get_imported_shader_aovs()
                if imported_aovs:
                    for item in imported_aovs:
                        ###TODO a typo here, _casuticmask_aov
                        if ('eyeCaustics' in plane_types['others'] or 'eyeGlint' in plane_types['others'])and \
                        (item[0].endswith('_casuticmask_aov') or item[0].endswith('_glint_aov')) and \
                        item[0] not in h_planes:
                            h_planes.append(item[0])
                            AOVS_PARM_MAP[item[0]] = {'vm_variable_plane':item[0],'vm_vextype_plane':item[1]}
        try:
            h_planes.remove('eyeCaustics')
            h_planes.remove('eyeGlint')
        except ValueError:
            pass

    #Get all the components that we use in this render.
    plane_types['direct']['comp'].extend(plane_types['indirect']['comp'])
    comps = list(set(plane_types['direct']['comp']))

    #Set components.
    components = ''
    for c in comps:
        if c in allowed_comps:
            components = '{0} {1} '.format(components, c)
    set_parms_in_take({'vm_exportcomponents':components.lower()}, mantra_ROP)
    #If there is no components, we remove all direct and indirect image planes
    if not comps:
        try:
            h_planes.remove('direct_comp')
            h_planes.remove('indirect_comp')
        except ValueError:
            pass

    #Set Image planes.
    set_parms_in_take({'vm_numaux':len(h_planes)}, mantra_ROP)
    for index, plane in enumerate(h_planes):
        index = index+1
        #Set regular parms
        set_parms_in_take({'vm_variable_plane{0}'.format(index):plane}, mantra_ROP)
        set_parms_in_take({'vm_lightexport{0}'.format(index):1}, mantra_ROP)

        #Set extra parms
        if plane in AOVS_PARM_MAP.keys():
            plane_settings = AOVS_PARM_MAP[plane]
            for setting in plane_settings:
                set_parms_in_take({'{0}{1}'.format(setting, index):AOVS_PARM_MAP[plane][setting]}, mantra_ROP)


def set_magic_shader_planes(mantra, magic_aovs):
    """
    Set extra image planes on the Mantra.
    This is different from the regular image planes.
    These image planes are main to be used
    for object matte.
    """
    mantra_ROP = hou.node('/out/{0}'.format(mantra.name))
    #We append those planes on the original planes list
    planes_len = mantra_ROP.parm('vm_numaux').eval()
    current_planes = [mantra_ROP.parm('vm_variable_plane{0}'.format(index+1)).eval() for index in range(planes_len)]

    set_parms_in_take({'vm_numaux':len(magic_aovs) + planes_len}, mantra_ROP)
    for aov in magic_aovs:
        index = current_planes.index(aov.aov_name) + 1 if aov.aov_name in current_planes else magic_aovs.index(aov) + planes_len + 1
        set_parms_in_take({'vm_variable_plane{0}'.format(index):aov.aov_name}, mantra_ROP)
        set_parms_in_take({'vm_vextype_plane{0}'.format(index):aov.storage_type}, mantra_ROP)


def set_parms_in_take(parmsDict, node = None):
    """
    Set values of parms in a take.
    parmsDict contains pairs of parms and values.
    ex.{'tx': '0', 'ty':'1', 'tz':2}
    If no node provided, the keys of parmDict have to be
    parm absolute paths.
    """
    for parm_name in parmsDict:
        if not node:
            node = hou.parm(parm_name).node()
        hou.hscript('takeinclude {0} {1}'.format(node.path(), parm_name))
        try:
            node.parm(parm_name).set(parmsDict[parm_name])
        except AttributeError:
            print 'Unable to set parameter: {0}/{1}'.format(node.path(), parm_name)


def _set_magic_aovs_in_take(a_rfxAsset, magic_aovs):
    #Get current AOVs that are in used, and append them.
    aovs = a_rfxAsset.get_magic_aovs()
    for magic_aov in magic_aovs:
        if magic_aov.aov_name not in [aov.aov_name for aov in aovs]:
            aovs.append(magic_aov)

    #This is just a way to unlock those multi parms in takes.
    set_parms_in_take({'magic_aovs':40}, a_rfxAsset.sesi_node)
    set_parms_in_take({'magic_mattes':40}, a_rfxAsset.sesi_node)
    hou.hscript('takeinclude {0} *magic_*'.format(a_rfxAsset.sesi_node.path()))
    a_rfxAsset.set_magic_aovs(aovs)
    a_rfxAsset.set_use_magic_shaders(True)


def list_to_string(a_list, exclude = False):
    """
    Convert a list items to houdini string
    """
    string = ''
    for item in a_list:
        if isinstance(item, RenderObject) or isinstance(item, RenderItem):
            item = item.obj_path
        string = '{0}^{1} '.format(string, item) if exclude else '{0}{1} '.format(string, item)

    return string


def create_tmp_geoms(mantra):
    """
    Create tmp geoms.
    We use this method when we render objects which are
    just part of the geometry (prim groups).
    For HRST group we create a OBJ node for it.
    """
    objects = mantra.objects
    merge_dict = {}

    for obj in objects:
        if not obj.obj_path == obj.HRST_path:
            tmp_subnet = hou.node(TMP_OBJ_SUBNET_PATH)
            if not tmp_subnet:
                tmp_subnet = hou.node('/obj/').createNode('subnet', TMP_OBJ_SUBNET_PATH.split('/')[-1])
            tmp_subnet.hide(True)
            tmp_subnet.setDisplayFlag(False)

            #Create Object Node
            objNode = tmp_subnet.node(obj.merge_SOP_name)
            if not objNode:
                # We have to copy all the object level settings to our new temp object
                objNode = hou.copyNodesTo( [ hou.node(obj.HRST_path) ], hou.node(TMP_OBJ_SUBNET_PATH) )[0]
                objNode.setName(obj.merge_SOP_name)
                for c in objNode.children(): c.destroy()

            #Create Object Merge SOP
            object_merge_SOP = objNode.node(obj.merge_SOP_name)
            if not object_merge_SOP:
                object_merge_SOP = objNode.createNode('object_merge', obj.merge_SOP_name)

            #Get the group name we want
            prim_group = obj.prim_group.split('_primGroups_')[-1] if obj.prim_group.startswith('_primGroups_') else obj.prim_group

            #Create a useful dictionary so we can put settings on the object_merge SOP easier.
            if not merge_dict.has_key(obj.merge_SOP_name):
                merge_dict[obj.merge_SOP_name] = {}
            if not merge_dict[obj.merge_SOP_name].has_key(obj.HRST_path):
                merge_dict[obj.merge_SOP_name][obj.HRST_path] = []

            merge_dict[obj.merge_SOP_name][obj.HRST_path].append(prim_group)

    #Set objects and groups
    for obj_name in merge_dict:
        for index, HRST_path in enumerate(merge_dict[obj_name]):
            object_merge_SOP = hou.node("{0}/{1}/{2}".format(TMP_OBJ_SUBNET_PATH, obj_name, obj_name))
            object_merge_SOP.parm('numobj').set(len(merge_dict[obj_name]))
            object_merge_SOP.parm('xformtype').set(1)
            object_merge_SOP.setRenderFlag(1)

            object_merge_SOP.parm('objpath{0}'.format(index+1)).set(HRST_path)

            for group in merge_dict[obj_name][HRST_path]:
                group = '{0} {1} '.format(object_merge_SOP.parm('group{0}'.format(index+1)).eval(), group)
                object_merge_SOP.parm('group{0}'.format(index+1)).set(group)

    #Unselect all temp nodes
    try:
        for node in hou.selectedNodes():
            node.setSelected(False)
    except:
        pass


def clean_tmp_geoms():
    tmp_subnet = hou.node(TMP_OBJ_SUBNET_PATH)
    if tmp_subnet:
        tmp_subnet.destroy()


def _get_eye_aov_name(aov_type):
    """
    Get the correct houdini image plane name for eyes.
    """
    pass
