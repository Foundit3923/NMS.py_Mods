import logging
import ctypes
import keyboard 
import pygetwindow as gw
import pymem
from typing import Optional
from dataclasses import dataclass, field

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
from pymhf.core.utils import set_main_window_focus
from nmspy.data.common import TkHandle, Vector3f, cTkMatrix34
#from nmspy.data import engine as engine, common, structs as nms_structs, local_types as lt

class Window:
    def __init__(self, name):
      self.name = name
      self.is_stored = False
      self.window = None
  
    def isWindowLaunched(self):
        logging.info(f'Checking if {self.name} is launched')
        if self.name in gw.getAllTitles():
            logging.info(f'{self.name} is launched\n')
            return True
        else:
            logging.info(f'{self.name} is not launched\n')
            return False
        
    def isWindowStored(self):
        logging.info(f'Checking if {self.name} window is stored')
        if self.window == None:
            logging.info(f'{self.name} window not stored\n')
            return False
        else:
            logging.info(f'{self.name} window is already stored\n\n')
            return True
        
    def storeWindow(self):
        if not self.isWindowStored():
            logging.info(f'Storing {self.name} window\n')
            self.window = gw.getWindowsWithTitle(self.name)[0]
            self.is_stored = True

    def isActiveWindow(self, log=True):
        if log: logging.info(f'Checking if {self.name} is active window')
        window = gw.getActiveWindow().title
        result = window == self.name
        if log: logging.info(f'{result}: {window} is the active window\n')
        return result

    def activateWindow(self):
        logging.info(f'Activating {self.name} window')
        if self.isWindowLaunched():
            if self.isWindowStored(): 
                if not self.isActiveWindow():
                    logging.info(f'Changing window focus to {self.name}')
                    self.window.activate()
                    logging.info(f'{self.name} is active window\n\n')
                else:
                    logging.info(f'{self.name} window is already activated\n\n')
            else:
                self.storeWindow()
                self.activateWindow()
        else:
            logging.info(f'Unable to activate {self.name} window')
            logging.info(f'{self.name} window is not launched. Launch window and try again.\n\n')

@dataclass
class State_Vars(ModState):
    application: nms_structs.cGcApplication = None
    binoculars: nms_structs.cGcBinoculars = None
    playerEnv: nms_structs.cGcPlayerEnvironment = None
    inputPort: nms_structs.cTkInputPort = None
    playerEnv_ptr: int = 0
    binoculars_ptr: int = 0
    inputPort_ptr: int = 0
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
        self.nms_window = Window("No Man's Sky")
        self.gui_window = Window("pyMHF")

    @on_state_change("APPVIEW")
    def init_state_var(self):
        logging.info("Setting State Vars")
        """ try:
            self.loadJson()
        except Exception as e:
            logging.exception(e)
        logging.info(f'wpDict: {self.state.wpDict}')
        sim_addr = ctypes.addressof(nms.GcApplication.data.contents.Simulation)
        self.state.binoculars = map_struct(sim_addr + 74160 + 6624, nms_structs.cGcBinoculars) """
        try:
            self.state.playerEnv = nms.GcApplication.data.contents.Simulation.environment.playerEnvironment 
        except Exception as e:
            logging.info("Unable to store playerEnv")
            logging.exception(e)
        self.nms_window = Window("No Man's Sky")
        self.nms_window.storeWindow()
        self.gui_window = Window("pyMHF")
        self.gui_window.storeWindow()
        logging.info(f'state var set ({self.name})')
        logging.info(f'\n')

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    @manual_hook(
        "cGcApplication::Update",
        #0x26C710,
        pattern="40 53 48 83 EC 20 E8 ?? ?? ?? ?? 48 89",
        func_def=FUNCDEF(
            restype=ctypes.c_ulonglong,
            argtypes=[]
        ),
        detour_time="after",
    ) #@main_loop.after
    def do_something(self):
        #logging.info("test")
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
        if self.state.start_pressing:
            logging.info(f'Eval in Main self.state.saved_wp_flag == {self.state.saved_wp_flag}')
            if self.counter < 100:
                if keyboard.is_pressed('f'):
                    keyboard.press('e')
                else:
                    logging.info(f'{self.counter}')
                    self.counter += 1
            else:
                keyboard.release('e')
                keyboard.release('f')
                self.state.start_pressing = False
                self.counter = 0
        if self.nms_window.isActiveWindow(False):
            if self.test_press: 
                logging.info("finishing test_press")
                #self.toggleFKey()
                #self.toggleFKey()
                #self.toggleFKey()
                keyboard.press_and_release('f')
                self.test_press = False
                #self.callSetButton()
   



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
        if self.state.bincoulars_ptr != this:
            logging.info(f'Setting self.state.binoculars')
            self.state.bincoulars_ptr = this
            #self.state.binoculars = map_struct(this, nms_structs.cGcBinoculars)


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
        #logging.info(f'Setting self.state.playerEnv')
        #self.state.playerEnv = (self.state.playerEnv_ptr, common.cTkMatrix34)
        #logging.info(f'{self.state.playerEnv[3]}') # type: ignore

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
        "cGcPlayer::cGcPlayer",
        pattern="48 89 5C 24 08 48 89 74 24 10 57 48 83 EC 50 0F 29 74 24 40 48 8B F9 E8",
        func_def=FUNC_CALL_SIGS["cGcPlayer::cGcPlayer"],
        detour_time="after",
    )
    def get_Player(self, this):
        logging.info(f'--------cGcPlayer::cGcPlayer captured at {this}')


    #cTkInputDeviceManager::ProcessMouse(cTkInputDeviceManager *this, struct cTkInputPort *)
    @one_shot
    @manual_hook(
        "cTkInputPort::SetButton",
        #offset=0x232BD80,
        pattern="40 57 48 83 EC 40 48 83 79 58",
        func_def=FUNC_CALL_SIGS["cTkInputPort::SetButton"],
        detour_time="after",
    )
    def get_inputPort(self, this, leIndex):
        logging.info("--------cTkInputPort::SetButton")
        logging.info(f'leIndex: {leIndex}')
        if self.state.inputPort_ptr != this:
            logging.info("Setting self.state.inputPort")
            self.state.inputPort_ptr = this
            self.state.inputPort = map_struct(self.state.inputPort_ptr, nms_structs.cTkInputPort)


    @on_key_pressed("f1")
    def toggle_window_focus(self):
        #logging.info(f'{keyboard._os_keyboard.from_name}')
        logging.info(f'F1 key pressed\n')
        set_main_window_focus()
        #self.toggle_gui_and_game()

    @on_key_pressed("j")
    def press_f(self):
        logging.info("J key pressed")
        logging.info(f'{self.state.playerEnv.mPlayerTM.pos.__json__()}')
        logging.info(f'{self.state.playerEnv.mPlayerTM.__str__()}')
        position = call_function("cGcPlayer::GetPosition", 
                                 pattern="0F 10 81 50 02 00 00 48")
        #set_main_window_focus()
        #logging.info(f'{pymem.Pymem(EXE_NAME).process_handle}')
        #if keyboard.is_pressed('f'):
        #    logging.info("release f")
        #    keyboard.release('f')
        #else:
        #    logging.info("press f")
        #    keyboard.press('f')


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
        if not self.nms_window.isActiveWindow(): 
            self.nms_window.activateWindow()
        if self.state.playerEnv == None:
            self.state.playerEnv = map_struct(self.state.playerEnv_ptr, nms_structs.cGcPlayerEnvironment)
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
        if not self.nms_window.isActiveWindow(): 
            self.nms_window.activateWindow()
        self.state.saved_wp_flag = True
        logging.info(f'Setting self.state.saved_wp_flag -> {self.state.saved_wp_flag}')
        logging.info(f'start processing: {self.state.start_pressing} -> True')
        self.state.start_pressing = True
    
#--------------------------------------------------------------------Methods----------------------------------------------------------------------------#

#------------------------------------------------------Window Management-------------------------------------------------------------#

    def toggle_gui_and_game(self):
        logging.info(f'Checking active window')
        if self.nms_window.isActiveWindow():
            logging.info(f'{self.nms_window.name} is the active window')
            self.gui_window.activateWindow()
        else:
            logging.info(f'{self.gui_window.name} is the active window')
            self.nms_window.activateWindow()

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
          self.state.wpDict[name] = self.state.playerEnv.mPlayerTM.pos.__json__()
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
            node_matrix = self.GetNodeTransMats(self.state.binoculars.MarkerModel)
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
            call_function(
                "Engine::ShiftAllTransformsForNode",
                self.state.binoculars.MarkerModel.lookupInt,
                ctypes.addressof(transformation_vector),
                pattern="40 53 48 83 EC 20 44 8B D1 44 8B C1")
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)
    
    """ def getNodeMatrix(self):
        node_matrix = engine.GetNodeAbsoluteTransMatrix(self.state.binoculars.MarkerModel)
        return node_matrix """
    
    def GetNodeTransMats(
        node: TkHandle,
        rel_mat: Optional[cTkMatrix34] = None,
        abs_mat: Optional[cTkMatrix34] = None,
    ) -> tuple[cTkMatrix34, cTkMatrix34]:
        if rel_mat is None:
            rel_mat = cTkMatrix34()
        if abs_mat is None:
            abs_mat = cTkMatrix34()
        call_function(
            "Engine::GetNodeTransMats",
            node.lookupInt,
            ctypes.addressof(rel_mat), # type: ignore
            ctypes.addressof(abs_mat), # type: ignore
            overload="TkHandle, cTkMatrix34 *, cTkMatrix34 *",
            pattern="40 56 48 83 EC 20 44 8B D1 44 8B C9 41 C1 EA 12 41 81 E1 FF FF 03 00 49 8B F0 4C"
        )
        return (rel_mat, abs_mat)
    
    def repackVector3f(self, dict_a):
      vector = common.Vector3f()
      vector.x = dict_a['x']
      vector.y = dict_a['y']
      vector.z = dict_a['z']
      return vector

    def toggleFKey(self):
        if keyboard.is_pressed('f'):
            logging.info("Release F")
            keyboard.release('f')
        else:
            logging.info("Press F")
            keyboard.press('f')

    def callSetButton(self):
        self.state.inputPort.SetButton(lt.eInputButton.EInputButton_KeyF)
#------------------------------------------------------Displaying Waypoint Data--------------------------------------------------------------#

    def print_available_waypoints(self):
        dict = self.state.wpDict
        count = 0
        logging.info(f'\nAvailable waypoints:')
        for key in dict:
            logging.info(f'{key}: {dict[key]}')
