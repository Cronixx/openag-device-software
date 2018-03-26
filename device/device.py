# Import python modules
import logging, time, json, threading

# Import device modes and errors
from device.utility.mode import Mode
from device.utility.error import Error

# Import device state manager
from device.state import State

# Import recipe handler
from device.recipe import Recipe

# Import database models
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()
from app.models import State as StateModel


class Device(object):
    """ A state machine that spawns threads to run recipes, read sensors, set 
    actuators, manage control loops, sync data, and manage external events. """

    # Initialize logger
    logger = logging.getLogger(__name__)

    # Initialize device mode and error
    _mode = None
    _error = None

    # Initialize state object, `state` serves as shared memory between threads
    # Note: Thread should be locked whenever writing to `state` object to 
    # avoid memory corruption.
    state = State()

    # Initialize environment state dict
    state.environment = {
        "sensor": {"desired": {}, "reported": {}},
        "actuator": {"desired": {}, "reported": {}},
        "reported_sensor_stats": {
        "individual": {
                "instantaneous": {},
                "average": {}
            },
            "group": {
                "instantaneous": {},
                "average": {}
            }
        }
    }

    # Initialize recipe state dict
    state.recipe = {
        "recipe": None,
        "start_timestamp_minutes": -1,
        "last_update_minute": -1
    }

    # Initialize thread objects
    recipe = None
    peripherals = {}
    controllers = {}


    def __init__(self):
        """ Initializes device. Loads stored state from database. """
        self.load_state()
        self.mode = Mode.INIT
        self.error = Error.NONE



    @property
    def mode(self):
        """ Gets device mode. """
        return self._mode


    @mode.setter
    def mode(self, value):
        """ Safely updates device mode in state object. """
        self._mode = value
        with threading.Lock():
            self.state.device["mode"] = value


    @property
    def error(self):
        """ Gets device error. """
        return self._error


    @error.setter
    def error(self, value):
        """ Safely updates device error in state object. """
        self._error = value
        with threading.Lock():
            self.state.device["error"] = value


    def commanded_mode(self):
        """ Checks for commanded mode in device state then returns 
            mode or None. """
        if "commanded_mode" in self.state.device:
            return self.state.device["commanded_mode"]
        else:
            return None

    def run(self):
        """ Runs device state machine. """
        self.logger.info("Starting state machine")
        while True:
            if self.mode == Mode.INIT:
                self.run_init_mode()
            elif self.mode == Mode.SETUP:
                self.run_setup_mode()
            elif self.mode == Mode.NOM:
                self.run_nom_mode()
            elif self.mode == Mode.CONFIG:
                self.run_config_mode()
            elif self.mode == Mode.ERROR:
                self.run_error_mode()
            elif self.mode == Mode.RESET:
                self.run_reset_mode()


    def run_init_mode(self):
        """ Runs initialization mode. Creates and spawns recipe, peripheral, and 
            controller threads, then transitions to SETUP. """
        self.logger.info("Entered INIT")
        self.initialize_recipe()
        self.initialize_peripherals()
        self.initialize_controllers()
        self.mode = Mode.SETUP


    def run_setup_mode(self):
        """ Runs setup mode. Waits for all peripheral threads to
            enter NOM, WARMING, or ERROR, then transitions to NOM. """

        # TODO: wait for recipe thread as well...

        self.logger.info("Entered SETUP")
        while not self.all_peripherals_ready():
            time.sleep(0.2)


        # Remove this
        with threading.Lock():
            self.state.recipe["commanded_recipe"] = json.load(open('device/data/recipe.json'))
            self.state.recipe["commanded_mode"] = Mode.LOAD


        self.mode = Mode.NOM


    def run_nom_mode(self):
        """ Runs normal operation mode. Updates device state summary and 
            stores device state in database. Transitions to RESET if 
            commanded. Transitions to ERROR on error."""
        self.logger.info("Entered NOM")

        while True:
            # Update periodically
            time.sleep(4) # seconds

            # Update device state summary
            self.update_device_state_summary()

            # Store system state in database
            self.store_state()

            # Check for reset signal
            if self.commanded_mode() == Mode.RESET:
                self.mode = Mode.RESET
                continue
            
            # Check for system error
            if self.mode == Mode.ERROR:
                continue


    def run_config_mode(self):
        """ Runs configuration mode. Loads config from local file then 
            transitions to INIT. """
        self.logger.info("Entered CONFIG")
        self.load_config_from_local_file()
        self.mode = Mode.INIT

 
    def run_reset_mode(self):
        """ Runs reset mode. Stops all threads then transitions to SETUP. """
        self.logger.info("Entered RESET")
        # TODO: Stop threads
        self.mode = Mode.SETUP


    def run_error_mode(self):
        """ Runs error mode. Waits for reset signal then transitions
            to RESET. """
        self.logger.info("Entered ERROR")
        while self.mode != Mode.RESET:
            time.sleep(0.1) # 100ms


    def load_state(self):
        """ Loads stored state from database if it exists. If not, loads
            config from local file. """

        # Load stored state from database if exists
        if StateModel.objects.filter(pk=1).exists():
            stored_state = StateModel.objects.filter(pk=1).first()

            # Load device state
            stored_device_state = json.loads(stored_state.device)
            self.state.device["config"] = stored_device_state["config"]

            # Load recipe state
            stored_recipe_state = json.loads(stored_state.recipe)
            self.state.recipe["recipe"] = stored_recipe_state["recipe"]
            self.state.recipe["start_timestamp_minutes"] = stored_recipe_state["start_timestamp_minutes"]
            self.state.recipe["last_update_minute"] = stored_recipe_state["last_update_minute"]

            # Load peripherals state
            stored_peripherals_state = json.loads(stored_state.peripherals)
            for peripheral_name in stored_peripherals_state:
                if "stored" in stored_peripherals_state[peripheral_name]:
                    self.state.peripherals[peripheral_name] = {}
                    self.state.peripherals[peripheral_name]["stored"] = stored_peripherals_state[peripheral_name]["stored"]

            # Load controllers state
            stored_controllers_state = json.loads(stored_state.controllers)
            for controller_name in stored_controllers_state:
                if "stored" in stored_controllers_state[controller_name]:
                    self.state.controllers[controller_name] = {}
                    self.state.controllers[controller_name]["stored"] = stored_controllers_state[controller_name]["stored"]
        else:
            # Load config from local file
            self.load_config_from_local_file()


    def store_state(self):
        """ Stores system state in local database. If state does not exist 
            in database, creates it. """

        if not StateModel.objects.filter(pk=1).exists():
            StateModel.objects.create(
                id=1,
                device = json.dumps(self.state.device),
                recipe = json.dumps(self.state.recipe),
                environment = json.dumps(self.state.environment),
                peripherals = json.dumps(self.state.peripherals),
                controllers = json.dumps(self.state.controllers),
            )
        else:
            StateModel.objects.filter(pk=1).update(
                device = json.dumps(self.state.device),
                recipe = json.dumps(self.state.recipe),
                environment = json.dumps(self.state.environment),
                peripherals = json.dumps(self.state.peripherals),
                controllers = json.dumps(self.state.controllers),
            )


    def load_config_from_local_file(self):
        """ Loads config file into device state. """
        self.state.device["config"] = json.load(open('device/data/config.json'))


    def initialize_recipe(self):
        """ Initializes recipe. Creates recipe object then 
            spawns recipe thread."""
        self.recipe = Recipe(self.state)
        self.recipe.spawn()


    def initialize_peripherals(self):
        """ Initializes peripherals. Creates peripheral objects from stored
            config then spawns peripheral threads. """
        self.create_peripherals()
        self.spawn_peripherals()


    def initialize_controllers(self):
        """ Initializes controllers. Creates controller objects from stored
            config then spawns controller threads. """
        self.create_controllers()
        self.spawn_controllers()


    def create_peripherals(self):
        """ Creates peripheral objects. """
        config = self.state.device["config"]
        
        if "peripherals" in config:
            for peripheral_name in config["peripherals"]:
                # Get peripheral module and class name
                module_name = "device.peripheral." + config["peripherals"][peripheral_name]["module"]
                class_name = config["peripherals"][peripheral_name]["class"]

                # Import peripheral library
                module_instance= __import__(module_name, fromlist=[class_name])
                class_instance = getattr(module_instance, class_name)

                # Create peripheral objects
                self.peripherals[peripheral_name] = class_instance(peripheral_name, self.state)


    def spawn_peripherals(self):
        """ Spawns peripheral threads. """
        for peripheral_name in self.peripherals:
            self.peripherals[peripheral_name].spawn()


    def create_controllers(self):
        """ Creates controller objects. """
        config = self.state.device["config"]
        
        if "controllers" in config:
            for controller_name in config["controllers"]:
                # Get controller module and class name
                module_name = "device.controller." + config["controllers"][controller_name]["module"]
                class_name = config["controllers"][controller_name]["class"]

                # Import controller library
                module_instance= __import__(module_name, fromlist=[class_name])
                class_instance = getattr(module_instance, class_name)

                # Create controller objects
                self.controllers[controller_name] = class_instance(controller_name, self.state)


    def spawn_controllers(self):
        """ Spawns controller threads. """
        for controller_name in self.controllers:
            self.controllers[controller_name].spawn()


    def all_peripherals_ready(self):
        """ Check that all peripheral threads are either in NOM, WARMING, or 
            ERROR modes. """
        for peripheral_name in self.state.peripherals:
            peripheral_state = self.state.peripherals[peripheral_name]
            if peripheral_state["mode"] != Mode.NOM and \
                peripheral_state["mode"] != Mode.WARMING and \
                peripheral_state["mode"] != Mode.ERROR:
                    self.logger.info("Waiting for peripherals to be ready")
                    return False
        return True


    def update_device_state_summary(self, recipe=True, thread_modes=True):
        """ Updates device state summary. Optionally logs summary. """

        summary = ""


        # Create recipe summary
        if recipe:
            pass
            # summary += "\n    Recipe: {}".format(self.state.recipe)
            # summary += "\n        Name: {}".format(self.state.recipe["name"])
            # summary += "\n        Started: {}".format(self.state.recipe["start_datestring"])
            # summary += "\n        Progress: {} %".format(self.state.recipe["percent_complete_string"])
            # summary += "\n        Time Elapsed: {}".format(self.state.recipe["time_elapsed_string"])
            # summary += "\n        Time Remaining: {}".format(self.state.recipe["time_remaining_string"])
            # summary += "\n        Phase: {}".format(self.state.recipe["phase"])
            # summary += "\n        Cycle: {}".format(self.state.recipe["cycle"])
            # summary += "\n        Environment: {}".format(self.state.recipe["environment_name"])
        
        # Create thread states summary
        # if thread_modes:
        #     summary += "\n    States:"
        #     summary += "\n        System: {}".format(self.mode)
        #     summary += "\n        Recipe: {}".format(self.state.recipe["mode"])
        #     for periph in self.peripheral_state:
        #         verbose_name = self.peripheral_state[periph]["verbose_name"]
        #         mode = self.peripheral_state[periph]["mode"]
        #         summary += "\n        {}: {}".format(verbose_name, mode)


        with threading.Lock():
            self.state.device["summary"] = summary
        
        self.logger.info(summary)





