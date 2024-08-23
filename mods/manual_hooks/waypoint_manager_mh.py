import logging
import ctypes
import keyboard 
import pygetwindow as gw
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
        self.test_press = False
        self.nms_window = Window("No Man's Sky")
        self.gui_window = Window("pyMHF")

    @on_state_change("APPVIEW")
    def init_state_var(self):
        try:
            self.loadJson()
        except Exception as e:
            logging.exception(e)
        logging.info(f'wpDict: {self.state.wpDict}')
        """ self.state.playerEnv = nms.GcApplication.data.contents.Simulation.environment.playerEnvironment        
        sim_addr = ctypes.addressof(nms.GcApplication.data.contents.Simulation)
        self.state.binoculars = map_struct(sim_addr + 74160 + 6624, nms_structs.cGcBinoculars) """
        self.nms_window = Window("No Man's Sky")
        self.nms_window.storeWindow()
        self.gui_window = Window("pyMHF")
        self.gui_window.storeWindow()
        logging.info(f'state var set ({self.name})')
        logging.info(f'\n')

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    @manual_hook(
        "cGcApplication::Update",
        0x26C710,
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
            0xD63F50,
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
            0xFFE8A0,
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
        offset=0x103D300,
        func_def=FUNC_CALL_SIGS["cGcSimulation::UpdateRender"],
        detour_time="after",
    )
    def get_player_environement(self, this):
        logging.info("TEST")
        if self.state.playerEnv_ptr != (this + 81638 + 2048):
            logging.info(f'Setting self.state.playerEnv')
            self.state.playerEnv_ptr = this + 81638 + 2048
            self.state.playerEnv = map_struct(self.state.playerEnv_ptr, nms_structs.cGcPlayerEnvironment)
            test = map_struct(self.state.playerEnv_ptr, common.cTkMatrix34)
            logging.info(f'test value: {self.state.playerEnv.mbIsNight}')


    #cTkInputDeviceManager::ProcessMouse(cTkInputDeviceManager *this, struct cTkInputPort *)
    @one_shot
    @manual_hook(
        "cTkInputDeviceManager::ProcessMouse",
        offset=0x232BD80,
        func_def=FUNC_CALL_SIGS["cTkInputDeviceManager::ProcessMouse"],
        detour_time="after",
    )
    def get_inputPort(self, this, inputPort):
        logging.info("cTkInputDeviceManager::ProcessMouse")
        if self.state.inputPort_ptr != inputPort:
            logging.info("Setting self.state.inputPort")
            self.state.inputPort_ptr = inputPort
            self.state.inputPort = map_struct(self.state.inputPort_ptr, nms_structs.cTkInputPort)


    @on_key_pressed("f1")
    def toggle_window_focus(self):
        #logging.info(f'{keyboard._os_keyboard.from_name}')
        logging.info(f'F1 key pressed\n')
        self.toggle_gui_and_game()

    @on_key_pressed("j")
    def press_f(self):
        logging.info("J key pressed")
        if keyboard.is_pressed('f'):
            logging.info("release f")
            keyboard.release('f')
        else:
            logging.info("press f")
            keyboard.press('f')

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
    def test_press(self):
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
            node_matrix = self.getNodeMatrix()
            node_vector = node_matrix.pos
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
            call_function("Engine::ShiftAllTransformsForNode", self.state.binoculars.MarkerModel.lookupInt, ctypes.addressof(transformation_vector))
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)
    
    def getNodeMatrix(self):
        node_matrix = engine.GetNodeAbsoluteTransMatrix(self.state.binoculars.MarkerModel)
        return node_matrix
    
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
