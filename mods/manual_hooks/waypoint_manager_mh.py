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

@dataclass
class State_Vars(ModState):
    application: nms_structs.cGcApplication = None
    binoculars: nms_structs.cGcBinoculars = None
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
        self.marker_lookup = None
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
        try:
            self.state.playerEnv = nms.GcApplication.data.contents.Simulation.environment.playerEnvironment 
        except Exception as e:
            logging.info("Unable to store playerEnv")
            logging.exception(e)
        logging.info(f'state var set ({self.name})')
        logging.info(f'\n')

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    """ @manual_hook(
        "cGcApplication::Update",
        #0x26C710,
        pattern="40 53 48 83 EC 20 E8 ?? ?? ?? ?? 48 89",
        func_def=FUNCDEF(
            restype=ctypes.c_ulonglong,
            argtypes=[]
        ),
        detour_time="after",
    ) """
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
            self.state.binoculars = map_struct(this, nms_structs.cGcBinoculars)
            logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')

    @disable
    @manual_hook(
            "cGcBinoculars::UpdateDiscoveryUI",
            #0xD63F50,
            pattern="48 8B C4 48 89 48 08 55 41 54 41 55",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::UpdateDiscoveryUI"],
            detour_time="after",
    ) #@hooks.cGcAtmosphereEntryComponent.ActiveAtmosphereEntry.after #offset 00D63350
    def binocDiscoveryUI(self, this, *args):
        logging.info(f'--------Binoc Discovery UI load')


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
        return this

    @manual_hook(
            "cGcBinoculars::SetMarker",
            #0xFFE8A0,
            pattern="40 55 41 56 48 8D AC 24 C8",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::SetMarker"],
            detour_time="after",
    )
    def checkSetMarker(self, this):
        logging.info(f'--------Set Marker event detected')
        logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')
        check = 0
        check += self.state.binoculars_ptr != this
        check += self.state.binoculars == None
        logging.info(f'check = {check}')
        if check:
            logging.info(f'Setting self.state.binoculars')
            self.state.binoculars_ptr = this
            self.state.binoculars = map_struct(this, nms_structs.cGcBinoculars)
            logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')


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
    @disable
    @one_shot               
    @manual_hook(
            "cGcApplication::Data::Data",
            #0xD63F50,
            pattern="48 89 5C 24 08 48 89 6C 24 10 48 89 74 24 18 57 48 83 EC 20 33 F6 48 C7 41 40",
            func_def=FUNC_CALL_SIGS["cGcApplication::Data::Data"],
            detour_time="after",
    )
    def capture_GcApplication(self, this):
        logging.info(f'--------cGcApplication::Data::Data captured at : {this}')
        #nms.GcApplication.data = map_struct(this, nms_structs.cGcApplication.data)
        if self.state.playerEnv_ptr == (this + 3849792 + 653104 + 81638 + 2048):
            logging.info(f'self.state.playerEnv_ptr matches Application offset {this + 3849792 + 653104 + 81638 + 2048}')

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
            logging.info("Setting self.state.inputPort")
            self.state.inputPort_ptr = this
            self.state.inputPort = map_struct(self.state.inputPort_ptr, nms_structs.cTkInputPort)

    @hooks.Engine.ShiftAllTransformsForNode.before
    def before_shift(self, *args):
        logging.info(f"Shift: {args}")   

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

    @on_key_pressed("y")
    def toggle_window_focus(self):
        logging.info(f'Y key pressed\n')
        set_main_window_focus()
        main_window = get_main_window()
        ctypes.windll.user32.UpdateWindow(main_window.getHandle())
        logging.info('Updated window')
        logging.info("start test press")
        self.state.start_pressing = True


    @on_key_pressed('u')
    def toogle_f(self):
        logging.info("U key pressed")
        #self.toggleFKey()
        #self.state.inputPort.SetButton(lt.eInputButton.EInputButton_KeyF)
        target_pos = (919, 514)
        main_window = get_main_window()
        logging.info(f'main window: {main_window}')
        gui_window = pwc.getWindowsWithTitle("pyMHF")[0]
        logging.info(f'gui window: {gui_window}')
        hwnd = main_window.getHandle()
        logging.info(f'main window hwnd: {hwnd}')
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetFocus(hwnd)


    @on_key_pressed("n")
    def on_n(self):
        self.state.start_pressing = False
        self.initial_input = False
        keyboard.release('g')
        keyboard.release('f')

    @on_key_pressed("h")
    def getvisorstate(self):
        self.state.playerEnv = map_struct(self.state.playerEnv_ptr, nms_structs.cGcPlayerEnvironment)
        try:
            mode = self.state.binoculars.emode
        except Exception as e:
            logging.error(e)
        logging.info(f'Binoc Mode: {mode}')
        none = None
        status = False
        try:
            status = call_function(
                "cGcGenericSectionConditionVisorActive::IsConditionTrue",
                none,
                pattern="48 8B 05 ?? ?? ?? ?? 48 8B 88 50 D9 65 00 48 85 C9 74 0B 83",
                )
        except Exception as e:
            logging.error(e)
        logging.info(f'Visor Status: {status}')


    @on_key_pressed("j")
    def press_f(self):
        logging.info("J key pressed")
        """ logging.info(f'player.position: {self.state.player.position}')
        #direct_position = map_struct((self.state.player_ptr + 592), common.cTkMatrix34)
        logging.info(f'direct position: {self.player_pos.pos.__json__()}') """   
        logging.info(f'inFocus: {set_main_window_focus()}')
        self.state.start_pressing = True
        self.initial_input = True



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
        if self.state.playerEnv == None and self.state.playerEnv_ptr != None:
            self.state.playerEnv = map_struct(self.state.playerEnv_ptr, nms_structs.cGcPlayerEnvironment)
        else:
            logging.error("PlayerEnv_ptr is not set.")
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
          self.state.wpDict[name] = self.player_pos.pos.__json__()
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
            destination_vector = common.Vector3f()
            node_vector = common.Vector3f()
            destination_pos = self.state.wpDict[location]
            destination_vector = self.repackVector3f(destination_pos)
            logging.info(f'destination_vector: ' + destination_vector.__str__())
            node_matrix = engine.GetNodeAbsoluteTransMatrix(self.state.binoculars.MarkerModel)
            logging.info(f'node_matrix: ' + node_matrix.__str__())
            node_vector = node_matrix.pos # type: ignore
            logging.info(f'node_vector: ' + node_vector.__str__())
            transformation_vector = destination_vector - node_vector
            logging.info(transformation_vector.__str__())
            self.moveWaypointToDestination(transformation_vector)
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)

    def moveWaypointToDestination(self, transformation_vector):
        try:
            logging.info(f'Move waypoint to destination')
            try:
                handle = self.state.binoculars.MarkerModel
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
