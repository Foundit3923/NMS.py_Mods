import logging
import ctypes
import keyboard 
import pygetwindow as gw
import pywinctl as pwc
import pymem
import win32gui
import win32process
from typing import Optional
from dataclasses import dataclass, field
import mouse
import time
from copy import deepcopy

import nmspy.data.functions.hooks as hooks
from pymhf.core.hooking import disable, on_key_pressed, on_key_release, manual_hook, one_shot
from pymhf.core.memutils import map_struct
import nmspy.data.structs as nms_structs
from nmspy.data.structs import cGcNGui
from pymhf.core.mod_loader import ModState
from nmspy import NMSMod
from nmspy.decorators import main_loop, on_state_change
from pymhf.core.calling import call_function
from pymhf.gui.decorators import gui_variable, gui_button, STRING
import nmspy.data.local_types as lt
from nmspy.data import common
import nmspy.common as nms
import nmspy.data.engine as engine
from pymhf.gui.gui import GUI
from pymhf.core._types import FUNCDEF
from nmspy.data.functions.call_sigs import FUNC_CALL_SIGS
from pymhf.core.utils import set_main_window_focus, get_main_window, is_main_window_foreground
from nmspy.data.common import TkHandle, Vector3f, cTkMatrix34
#from nmspy.data import engine as engine, common, structs as nms_structs, local_types as lt

class cGcBinoculars(ctypes.Structure):
    MarkerModel: common.TkHandle

cGcBinoculars._fields_ = [
    ("_padding0", ctypes.c_ubyte * 472),
    ("MarkerModel", common.TkHandle),
]

@dataclass
class State_Vars(ModState):
    application: nms_structs.cGcApplication = None
    binoculars: cGcBinoculars = None
    playerEnv: nms_structs.cGcPlayerEnvironment = None
    inputPort: nms_structs.cTkInputPort = None
    player: nms_structs.cGcPlayer = None
    #scanner: nms_structs.cGcScanner = None

    playerEnv_ptr: int = 0
    player_ptr: int = 0
    binoculars_ptr: int = 0
    inputPort_ptr: int = 0
    #scanner_ptr: int = 0
    start_pressing: bool = False
    saved_wp_flag: bool = False
    wpDict: dict = field(default_factory = dict)
    _save_fields_ = ("wpDict", )

@disable
class WaypointManagerMod(NMSMod):
    __author__ = "foundit"
    __description__ = "Place markers at stored waypoints of places you've been"
    __version__ = "0.4"
    __NMSPY_required_version__ = "0.7.0"

    state = State_Vars()
    player_ptr = state.player_ptr

#--------------------------------------------------------------------Init----------------------------------------------------------------------------#

    def __init__(self):
        super().__init__()
        self.name = "WaypointManagerMod"
        self.should_print = False
        self.counter = 0
        self.capture = False
        self.lookupInt: common.TkHandle = None
        self.node_matrix: common.cTkMatrix34 = None
        self.node_pos: common.Vector3f = None
        self.text = ""
        #self.last_saved_flag = False
        self.fallingMarker = False
        #self.gui_storage = gui
        self.test_press: bool = False
        self.player_pos: common.cTkMatrix34 = None
        self.initial_input = False
        self.initial_input_count = 0
        self.end_initial_input = False
        self.ready_for_input = False
        self.f_press_confirmed = False
        self.e_press_confirmed = False
        self.marker_state = False

    @on_state_change("APPVIEW")
    def init_state_var(self):
        logging.info("Setting State Vars")
        try:
            self.loadJson()
        except Exception as e:
            logging.exception(e)
        logging.info(f'wpDict: {self.state.wpDict}')
        """sim_addr = ctypes.addressof(nms.GcApplication.data.contents.Simulation)
        self.state.binoculars = map_struct(sim_addr + 74160 + 6624, nms_structs.cGcBinoculars) """
        logging.info(f'state var set ({self.name})')
        logging.info(f'\n')

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    @main_loop.before
    def do_something(self):
        #logging.info("test")
        #Processes that require main window focus
        if self.state.start_pressing:
            pressed = keyboard.is_pressed('g')
            if not keyboard.is_pressed('g') and self.initial_input:
                keyboard.press('g')
                self.initial_input = False
            if self.ready_for_input:
                if not keyboard.is_pressed('f'):
                    keyboard.press('f') 
                logging.info(f'{self.counter}, {self.f_press_confirmed}')
                if self.counter < 100:
                    if self.f_press_confirmed:
                        if self.e_press_confirmed:
                            logging.info("pressing f and e")
                        else:
                            logging.info("pressing f")
                            if self.counter > 20:
                                keyboard.press('e')
                    else:
                        keyboard.press('f') 
                    self.counter += 1
                else:
                    logging.info("self.counter > 100")
                    keyboard.release('e')
                    keyboard.release('f')
                    self.e_press_confirmed = False
                    self.f_press_confirmed = False
                    self.state.start_pressing = False
                    self.ready_for_input = False
                    self.counter = 0
                    
            if is_main_window_foreground():
                keyboard.release('g')
                self.ready_for_input = True
                #if not keyboard.is_pressed('f'):
                #    keyboard.press('f')
        #Processes that do not require main window focus
        if self.fallingMarker:
            logging.info(f'counter: {self.counter}')
            if self.counter < 100:
                self.counter += 1
            else:
                self.counter = 0
                logging.info(f'self.moveWaypoint("{self.text}")')
                self.moveWaypoint(self.text)
                logging.info("Setting self.state.saved_wp_flag == False")
                self.state.saved_wp_flag = False
                self.fallingMarker = False
            
    @disable
    @one_shot
    @manual_hook(
            "cGcBinoculars::Update",
            #0xD63F50,
            pattern="40 55 53 56 41 55 41 56 48 8D AC 24 60",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::Update"],
            detour_time="after",
    ) #@hooks.cGcAtmosphereEntryComponent.ActiveAtmosphereEntry.after #offset 00D63350
    def binocUpdate(self, this, *args):
        logging.info(f'--------Binoc Update')
        logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')
        check = 0
        check += self.state.binoculars_ptr != this
        check += self.state.binoculars == None
        logging.info(f'check = {check}')
        if check:
            logging.info(f'Setting self.state.binoculars')
            self.state.binoculars_ptr = this
            self.state.binoculars = map_struct(this, cGcBinoculars)
            logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')


    @manual_hook(
            "cGcAtmosphereEntryComponent::ActiveAtmosphereEntry",
            #0xD63F50,
            pattern="48 89 5C 24 08 57 48 81 EC 80 00 00 00 65 48 8B 04 25 58 00 00 00 48 8B D9",
            func_def=FUNCDEF(
                restype=ctypes.c_int64,
                argtypes=[
                    ctypes.c_int64,
                ]
            ),
            detour_time="after",
    ) #@hooks.cGcAtmosphereEntryComponent.ActiveAtmosphereEntry.after #offset 00D63350
    def detectFallingMarker(self, this):
        logging.info(f'--------Falling Marker event detected')
        try:
            logging.info(f'self.state.saved_wp_flag == {self.state.saved_wp_flag}')
            if self.state.saved_wp_flag:
              self.fallingMarker = True
              logging.info(f'self.fallingMarker == {self.fallingMarker}')
        except Exception as e:
            logging.exception(e)
        self.capture = False
        return this
    
    @manual_hook(
            "cTkHmdOpenVR::GetInstance",
            pattern="E8 ?? ?? ?? ?? 38 58 15",
            func_def=FUNCDEF(
                restype=ctypes.c_int64,
                argtypes=[
                    ctypes.c_int64,
                ]
            ),
            detour_time="after",
    )
    def checkcTkHmdOpenVRGetInstance(self, this):
        logging.info(f'cTkHmdOpenVR::GetInstance hook is working')

    @manual_hook(
            "cGcBinoculars::SetMarker_lambda",
            pattern="48 8B C4 48 89 58 18 89 50 10 55 56 57 48",
            func_def=FUNCDEF(
                restype=ctypes.c_int64,
                argtypes=[
                    ctypes.c_int64,
                    ctypes.c_uint32,
                    ctypes.c_int64,
                ]
            ),
            detour_time="after",
    )
    def checkSetMarkerLambda(self, this, miLookupInt, matrix34):
        logging.info(f'SetMarker_Lambda hook is working')
        logging.info(f'Setting lookupInt: {miLookupInt}')
        self.lookupInt = TkHandle()
        self.lookupInt.lookupInt = miLookupInt
        logging.info(f'lookupInt: {self.lookupInt}')
        self.node_matrix = map_struct(matrix34, common.cTkMatrix34)
        logging.info(f'Node Matrix: {self.node_matrix.__str__()}')
        self.node_pos = deepcopy(self.node_matrix.pos)
        logging.info(f'Node Position: {self.node_pos.__str__()}')

        

    @manual_hook(
            "cGcBinoculars::SetMarker",
            #0xFFE8A0,
            pattern="40 55 41 56 48 8D AC 24 C8",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::SetMarker"],
            detour_time="before",
    )
    def checkSetMarker(self, this):
        logging.info(f'--------Set Marker event detected')
        logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')
        self.capture = True
        self.marker_state = True
        check = 0
        check += self.state.binoculars_ptr != this
        check += self.state.binoculars == None
        B = map_struct(this, cGcBinoculars)
        logging.info(f'check = {check}')
        if check:
            logging.info(f'Setting self.state.binoculars')
            self.state.binoculars_ptr = this
            self.state.binoculars = map_struct(this, cGcBinoculars)
            logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')
        logging.info(f'B.MarkerModel.lookupIntt: {B.MarkerModel.lookupInt}')
        logging.info(f'self.state.binoculars.MarkerModel.lookupInt: {self.state.binoculars.MarkerModel.lookupInt}')



    @one_shot
    @manual_hook(
        "cGcSimulation::UpdateRender",
        #offset=0x103D300,
        pattern="48 8B C4 48 89 58 08 48 89 68 10 48 89 70 18 57 48 81 EC E0 00 00 00 48 8B F1",
        func_def=FUNC_CALL_SIGS["cGcSimulation::UpdateRender"],
        detour_time="after",
    )
    def get_player_environement(self, this):
        logging.info(f'--------cGcSimulation::UpdateRender captured at {this}')
        if self.state.playerEnv_ptr != (this + 81638 + 2048):
            logging.info(f'Setting self.state.playerEnv')
            self.state.playerEnv_ptr = this + 81638 + 2048
            self.state.playerEnv = map_struct(self.state.playerEnv_ptr, nms_structs.cGcPlayerEnvironment)
            test = map_struct(self.state.playerEnv_ptr, common.cTkMatrix34)
            logging.info(f'test value: {self.state.playerEnv.mbIsNight}')

    @one_shot
    @manual_hook(
        "cGcApplication::GetSimulation",
        pattern="48 8B 41 38 48 05 20",
        func_def=FUNC_CALL_SIGS["cGcApplication::GetSimulation"],
        detour_time="after",
    )
    def get_application(self, this):
        logging.info(f'--------cGcApplication::GetSimulation captured at {this}')
        if self.state.playerEnv_ptr != (this + 81638 + 2048):
            logging.info(f'Setting self.state.application')
            self.state.application = map_struct(this + 0x50, nms_structs.cGcApplication)

    @one_shot
    @manual_hook(
        "cGcPlayer::GetPosition",
        pattern="0F 10 81 50 02 00 00 48",
        func_def=FUNC_CALL_SIGS["cGcPlayer::GetPosition"],
        detour_time="after",
    )
    def player_update_control(self, this, *args):
        logging.info(f'cGcPlayer.GetPosition hook working')
        if self.state.player == None or self.state.player_ptr != this:
            self.state.player_ptr = this
            self.state.player = map_struct(this, nms_structs.cGcPlayer)
            logging.info(f'Storing self.state.player')
            self.player_pos = map_struct((this + 592), common.cTkMatrix34)
            logging.info(f'Storing self.player_pos: {self.player_pos.__str__()}')
            self.state.binoculars = map_struct((this + 6512), cGcBinoculars)
            logging.info(f'Storing self.state.binoculars')
            logging.info(f'binoculars: {self.state.binoculars}')
            logging.info(f'binoculars.MarkerModel.lookupInt: {self.state.binoculars.MarkerModel.lookupInt}')




    #cTkInputDeviceManager::ProcessMouse(cTkInputDeviceManager *this, struct cTkInputPort *)
    #@disable
    @manual_hook(
        "cTkInputPort::SetButton",
        #offset=0x232BD80,
        pattern="40 57 48 83 EC 40 48 83 79 58",
        func_def=FUNC_CALL_SIGS["cTkInputPort::SetButton"],
        detour_time="after",
    )
    def get_inputPort(self, this, leIndex):
        #logging.info("--------cTkInputPort::SetButton")
        #logging.info(f'leIndex: {leIndex}')
        if leIndex == 101:
            self.e_press_confirmed = True
        if leIndex == 102:
            self.f_press_confirmed = True
        if self.state.inputPort_ptr != this:
            #logging.info("Setting self.state.inputPort")
            self.state.inputPort_ptr = this
            self.state.inputPort = map_struct(self.state.inputPort_ptr, nms_structs.cTkInputPort)   
    
    @hooks.Engine.ShiftAllTransformsForNode.before
    def before_shift(self, *args):
        logging.info(f"Shift: {args}")   

    #@disable
    @hooks.Engine.GetNodeAbsoluteTransMatrix.before
    def getNodeMatrix(self, miLookupInt, matrix):
        if self.capture and miLookupInt == self.state.binoculars.MarkerModel.lookupInt:
            logging.info("GetNodeAbsoluteTransMatrix hook working")
            logging.info(f"lookupInt: {miLookupInt}, Shift: {matrix}") 
            
    
    @hooks.Engine.SetNodeActivation.before
    def captureNodeActivation(self, *args):
        if self.capture:
            logging.info(f'Node active {args}')


    @one_shot
    @manual_hook(
        "cGcPlayer::UpdateScanning",
        #offset=0x232BD80,
        pattern="48 8B C4 48 89 58 20 F3 0F 11 48 10 55 56 57 41 54 41 55 41 56 41 57 48 8D A8 B8",
        func_def=FUNC_CALL_SIGS["cGcPlayer::UpdateScanning"],
        detour_time="after",
    )
    def capture_player(self, this, val):
        logging.info("--------UpdateScanning hook working")
        logging.info("Setting self.state.player_ptr")
        self.state.player_ptr = this
        player_ptr = this

    @on_key_pressed("j")
    def setcapture(self):
        player_pos = map_struct((self.state.player_ptr + 592), common.cTkMatrix34)
        logging.info(f'Player pos: {player_pos}')
        logging.info(f'LookupInt: {self.state.binoculars.MarkerModel.lookupInt}')

        """ node_matrix = common.cTkMatrix34()
        handle = self.state.binoculars.MarkerModel
        lookupInt = handle.lookupInt
        check = (lookupInt & 0xFFFC0000) != 0 and (lookupInt & 0x3FFFF) != 0x3FFFF
        logging.info(f'lookupInt check: {check}')
        node_matrix = engine.GetNodeAbsoluteTransMatrix(handle)
        logging.info(f'MarkerModel: {handle}')
        logging.info(f'node_matrix: ' + node_matrix.__str__()) """

    @on_key_pressed("u")
    def getmarkermatrix(self):
        logging.info("U key pressed")
        self.capture = False
        markermodel = map_struct(ctypes.addressof(self.state.binoculars) + 0x760, common.TkHandle)
        logging.info(f'markerModel: {markermodel.lookupInt}')
        bMarkerModel = self.state.binoculars.MarkerModel
        logging.info(f'bmarkerModel: {bMarkerModel.lookupInt}')
        logging.info(f'Node AbsTransMat(markermodel): {engine.GetNodeAbsoluteTransMatrix(markermodel)}')
        logging.info(f'Node AbsTransMat(bMarkerModel): {engine.GetNodeAbsoluteTransMatrix(bMarkerModel)}')
        markermodel.lookupInt = self.lookupInt
        logging.info(f'self.lookupInt: {markermodel.lookupInt}')
        logging.info(f'Node AbsTransMat(self.lookupInt): {engine.GetNodeAbsoluteTransMatrix(markermodel)}')

        #self.marker_state = not self.marker_state
        #engine.SetNodeActivation(self.state.binoculars.MarkerModel.lookupInt, self.marker_state)
        #engine.SetNodeActivation(self.lookupInt, self.marker_state)




#-----------------------------------------------------------------GUI Elements-------------------------------------------------------------------------#
    
    @gui_button("INIT self values")
    def init_values(self):
        self.should_print = False
        self.counter = 0
        self.marker_lookup = None
        self.text = ""
        self.state.saved_wp_flag = False
        self.fallingMarker = False
        self.print_values()

    @gui_button("Test Key Press")
    def test_press_button(self):
        self.test_press = True
        if not self.nms_window.isActiveWindow():
            self.nms_window.activateWindow()

    @gui_button("Print saved waypoints")
    def print_waypoints(self):
        self.print_available_waypoints()

    @property
    @STRING("Save waypoint as: ")
    def option_replace(self):
        return self.text

    @option_replace.setter
    def option_replace(self, location_name):
        self.text = location_name
        set_main_window_focus()
        self.storeLocation(location_name)

    @property
    @STRING("Remove waypoint: ")
    def remove_waypoint(self):
        return self.text

    @remove_waypoint.setter
    def remove_waypoint(self, location_name):
        del self.state.wpDict[location_name]
        self.updateJson()
        if not self.state.wpDict[location_name]:
            logging.info(f'Successfully removed Waypoint: {location_name}')

    @property
    @STRING("Load waypoint:")
    def load_waypoint_by_name(self):
        return self.text

    @load_waypoint_by_name.setter
    def load_waypoint_by_name(self, waypoint_name):
        self.text = waypoint_name
        logging.info("set_main_window_focus()")
        set_main_window_focus()
        self.initial_input = True
        self.state.saved_wp_flag = True
        logging.info(f'Setting self.state.saved_wp_flag -> {self.state.saved_wp_flag}')
        logging.info(f'start processing: {self.state.start_pressing} -> True')
        self.state.start_pressing = True
    
#--------------------------------------------------------------------Methods----------------------------------------------------------------------------#

#--------------------------------------------------Storing and Loading JSON----------------------------------------------------------#

    def loadJson(self):
        try:
          logging.info(f'Loading dict from local JSON file')
          logging.info(f'self.state.load("waypoint_data.json")')
          self.state.load("waypoint_data.json")
        except FileNotFoundError:
            logging.info(f'self.updateJson()')
            self.updateJson()

    def updateJson(self):
        try:
          logging.info(f'Save waypoint locations to local file')
          logging.info(f'self.state.save(\'waypoint_data.json\')')
          self.state.save('waypoint_data.json')
          logging.info(f'dict saved to waypoint_data.json')
        except Exception as e:
                logging.exception(e)

    def storeLocation(self, name):
        try:
          logging.info(f'Save waypoint location to dictionary, then update JSON')
          player_pos = map_struct((self.state.player_ptr + 592), common.cTkMatrix34)
          self.state.wpDict[name] = player_pos.right.__json__()
          self.updateJson()
          logging.info(f'\n')
          return dict
        except Exception as e:
                logging.exception(e) 

    def printDict(self):
        logging.info(self.state.wpDict)

#------------------------------------------------------Moving Waypoint--------------------------------------------------------------#

    def moveWaypoint(self, location):
        try:
            logging.info(f'Moving marker')
            MarkerModel = map_struct(ctypes.addressof(self.state.binoculars) + 0x760, common.TkHandle)
            destination_vector = common.Vector3f()
            node_vector = common.Vector3f()
            destination_pos = self.state.wpDict[location]
            destination_vector = self.repackVector3f(destination_pos)
            logging.info(f'destination_vector: ' + destination_vector.__str__())
            node_matrix = engine.GetNodeAbsoluteTransMatrix(MarkerModel)
            logging.info(f'node_matrix: ' + node_matrix.__str__())
            node_vector = node_matrix.pos # type: ignore
            logging.info(f'node_vector: {node_vector.__json__()}')
            transformation_vector = destination_vector - node_vector
            logging.info(f'transformation_vector: ' + transformation_vector.__str__())
            self.moveWaypointToDestination(transformation_vector, MarkerModel)
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)

    def moveWaypointToDestination(self, transformation_vector, handle):
        try:
            logging.info(f'Move waypoint to destination')
            try:
                engine.ShiftAllTransformsForNode(handle, transformation_vector)
            except:
                import traceback
                logging.exception(traceback.format_exc())
        except Exception as e:
                logging.exception(e)
    
    def repackVector3f(self, dict_a):
      vector = common.Vector3f()
      vector.x = dict_a['x']
      vector.y = dict_a['y']
      vector.z = dict_a['z']
      return vector

#------------------------------------------------------Displaying Waypoint Data--------------------------------------------------------------#

    def print_available_waypoints(self):
        dict = self.state.wpDict
        count = 0
        logging.info(f'\nAvailable waypoints:')
        for key in dict:
            logging.info(f'{key}: {dict[key]}')
