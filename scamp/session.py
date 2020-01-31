from .transcriber import Transcriber
from ._midi import *
from .instruments import Ensemble, ScampInstrument
from clockblocks import Clock, current_clock
from .utilities import SavesToJSON
from ._dependencies import pynput, pythonosc
from threading import Thread, current_thread


class Session(Clock, Ensemble, Transcriber, SavesToJSON):

    def __init__(self, tempo=60, default_soundfont="default", default_audio_driver="default",
                 default_midi_output_device="default"):
        """
        A Session combines the functionality of a master clock, an ensemble, and a transcriber.

        :param tempo: the initial tempo of the master clock
        :type tempo: float
        :param default_soundfont: the default soundfont used by instruments in this session. (Can be overridden at
            instrument creation.)
        :type default_soundfont: string
        :param default_audio_driver: the default driver used by (soundfont) instruments to output audio. (Can be
            overridden at instrument creation.)
        :type default_audio_driver: string
        :param default_midi_output_device: the default midi_output_device for outgoing midi streams. (Again, can be
            overridden at instrument creation.)
        :type default_midi_output_device: string or int
        """

        Clock.__init__(self, name="MASTER", initial_tempo=tempo)
        Ensemble.__init__(self, default_soundfont=default_soundfont, default_audio_driver=default_audio_driver,
                          default_midi_output_device=default_midi_output_device)
        Transcriber.__init__(self)

        # A policy for spelling notes used as the default for the entire session
        # Useful if the entire session is in a particular key, for instance
        self._default_spelling_policy = None
        self._listeners = {"midi": {}, "osc": {}}

    def run_as_server(self):
        """
        Runs this session on a parallel thread so that it can act as a server. This is the approach that should be taken
        if running scamp from an interactive terminal session. Simply type "s = Session().run_as_server()"

        :return: self
        """
        def run_server():
            current_thread().__clock__ = self
            while True:
                current_clock().wait_forever()

        Thread(target=run_server, daemon=True).start()
        # don't have the thread that called this recognize the Session as its clock anymore
        current_thread().__clock__ = None
        return self

    # ----------------------------------- Listeners ----------------------------------

    @staticmethod
    def get_available_midi_input_devices():
        """
        Returns a list of available ports and devices for midi input.
        """
        return get_available_midi_input_devices()

    @staticmethod
    def print_available_midi_input_devices():
        """
        Prints a list of available ports and devices for midi input.
        """
        return print_available_midi_input_devices()

    def register_midi_listener(self, port_number_or_device_name, callback_function):
        """
        Register a callback_function to respond to incoming midi events from port_number_or_device_name

        :param port_number_or_device_name: either the port number to be used, or an device name for which the port
            number will be determined. (Fuzzy string matching is used to pick the device with closest name.)
        :param callback_function: the callback function used when a new midi event arrives. Should take either one
            argument (the midi message) or two arguments (the midi message, and the dt since the last message)
        """
        port_number = get_port_number_of_midi_device(port_number_or_device_name, "input") \
            if isinstance(port_number_or_device_name, str) else port_number_or_device_name

        if port_number is None:
            raise ValueError("Could not find matching MIDI device.")
        elif port_number not in (x[0] for x in get_available_midi_input_devices()):
            raise ValueError("Invalid port number for midi listener.")

        if port_number in self._listeners["midi"]:
            self.remove_midi_listener(port_number)
        self._listeners["midi"][port_number] = start_midi_listener(port_number, callback_function, clock=self)

    def remove_midi_listener(self, port_number_or_device_name):
        """
        Removes the midi listener with the given port_number_or_device_name

        :param port_number_or_device_name: either the port number to be used, or an device name for which the port
            number will be determined. (Fuzzy string matching is used to pick the device with closest name.)
        """
        port_number = get_port_number_of_midi_device(port_number_or_device_name, "input") \
            if isinstance(port_number_or_device_name, str) else port_number_or_device_name
        if port_number not in self._listeners["midi"]:
            raise ValueError("No midi listener to remove on port", port_number)
        self._listeners["midi"][port_number].close_port()
        del self._listeners["midi"][port_number]

    def register_osc_listener(self, port, osc_address_pattern, callback_function, ip_address="127.0.0.1"):
        """
        Register a callback function for OSC messages on a given address/port with given pattern

        :param port: port on which to receive messages
        :param osc_address_pattern: address pattern to respond to (e.g. "/gesture/start")
        :param callback_function: function to call upon receiving a message. The first argument of the function will
            be the address, and the remaining arguments will be those passed along in the osc message.
        :param ip_address: ip address on which to receive messages
        """
        if pythonosc is None:
            raise ImportError("Package python-osc not found; cannot set up osc listener.")

        def callback_wrapper(*args, **kwargs):
            self.rouse_and_hold()
            threading.current_thread().__clock__ = self
            callback_function(*args, **kwargs)
            threading.current_thread().__clock__ = None
            self.release_from_suspension()

        if (ip_address, port) not in self._listeners["osc"]:
            dispatcher = pythonosc.dispatcher.Dispatcher()
            self._listeners["osc"][(ip_address, port)] = {
                "server": pythonosc.osc_server.ThreadingOSCUDPServer((ip_address, port), dispatcher),
                "dispatcher": dispatcher
            }
            self.fork_unsynchronized(self._listeners["osc"][(ip_address, port)]["server"].serve_forever, args=(0.001, ))

        self._listeners["osc"][(ip_address, port)]["dispatcher"].map(osc_address_pattern, callback_wrapper)

    def remove_osc_listener(self, port, ip_address="127.0.0.1"):
        """
        Remove OSC listener on the given port and IP address

        :param port: port of the listener to remove
        :param ip_address: ip_address of the listener to remove
        """
        if (ip_address, port) in self._listeners["osc"]:
            self._listeners["osc"][(ip_address, port)]["server"].shutdown()
            del self._listeners["osc"][(ip_address, port)]

    def register_keyboard_listener(self, on_press=None, on_release=None, suppress=False, **kwargs):
        """
        Register a callback_function to respond to incoming keyboard events

        :param on_press: function taking two arguments: key name (string) and key number (int) called on key down
        :param on_release: function taking two arguments: key name (string) and key number (int) called on key up
        :param suppress: if true, keyboard events are consumed and not passed on to other processes
        """
        if pynput is None:
            raise ImportError("Cannot use keyboard input because package pynput was not found. "
                              "Install pynput and try again.")
        self.remove_keyboard_listener()  # in case one is already running

        keys_down = []
        if on_press is not None:
            # if on_press is defined, place a wrapper around it that wakes up the the Session when it's called
            def on_press_wrapper(key_argument):
                self.rouse_and_hold()
                threading.current_thread().__clock__ = self
                name, number = Session._name_and_number_from_key(key_argument)
                if name not in keys_down:
                    keys_down.append(name)
                    on_press(name, number)
                threading.current_thread().__clock__ = None
                self.release_from_suspension()
        else:
            on_press_wrapper = None
        if on_release is not None:
            # if on_release is defined, place a wrapper around it that wakes up the the Session when it's called
            def on_release_wrapper(key_argument):
                self.rouse_and_hold()
                threading.current_thread().__clock__ = self
                name, number = Session._name_and_number_from_key(key_argument)
                if name in keys_down:
                    keys_down.remove(name)
                on_release(name, number)
                threading.current_thread().__clock__ = None
                self.release_from_suspension()
        else:
            # otherwise, in case we defined on_press, we need to make sure to remove the key from key down anyway
            def on_release_wrapper(key_argument):
                name, number = Session._name_and_number_from_key(key_argument)
                if name in keys_down:
                    keys_down.remove(name)

        listener = pynput.keyboard.Listener(on_press=on_press_wrapper, on_release=on_release_wrapper,
                                            suppress=suppress, **kwargs)
        listener.start()
        self._listeners["keyboard"] = listener

    def remove_keyboard_listener(self):
        """
        Remove a previously added keyboard listener
        """
        if "keyboard" in self._listeners:
            self._listeners["keyboard"].stop()
            del self._listeners["keyboard"]

    @staticmethod
    def _name_and_number_from_key(key_or_key_code):
        # converts the irritating system within pynput to a simple key name and key number
        # TODO: FIX KEY CODES? Why is 'o' the same as space?
        if key_or_key_code is None:
            name = number = None
        elif isinstance(key_or_key_code, pynput.keyboard.Key):
            name = key_or_key_code.name
            number = key_or_key_code.value.vk
        else:
            # it's KeyCode
            name = key_or_key_code.char
            number = key_or_key_code.vk
        return name, number

    def register_mouse_listener(self, on_move=None, on_press=None, on_release=None, on_scroll=None,
                                suppress=False, relative_coordinates=False, **kwargs):
        """
        Register a callback_function to respond to incoming mouse events

        :param on_move: callback function taking two arguments (x, y) called when the mouse is moved
        :param on_press: callback function taking three arguments: (x, y, button), where button is one of
            "left", "right", or "middle"
        :param on_release: callback function taking three arguments: (x, y, button), where button is one of
            "left", "right", or "middle"
        :param on_scroll: callback function taking four arguments: (x, y, dx, dy)
        :param relative_coordinates: if True (requires tkinter library), x and y values are normalized to screen width
            and height and are floating point. Otherwise they are ints in units of pixels.
        :param suppress: if true, mouse events are consumed and not passed on to other processes
        """
        if pynput is None:
            raise ImportError("Cannot use mouse input because package pynput was not found. "
                              "Install pynput and try again.")
        self.remove_mouse_listener()  # in case one is already running

        if relative_coordinates:
            try:
                import tkinter as tk
            except ImportError:
                raise ImportError("Cannot use relative coordinates, since the tkinter library is required for"
                                  "determining the screen size.")
            root = tk.Tk()
            x_scale = 1 / root.winfo_screenwidth()
            y_scale = 1 / root.winfo_screenheight()
        else:
            x_scale = y_scale = 1

        # on_move and on_scroll are surrounded with a very simple wrapper that rouses the session and defines it as
        # the current clock on the thread of the callback function
        if on_move is not None:
            def on_move_wrapper(x, y):
                self.rouse_and_hold()
                threading.current_thread().__clock__ = self
                on_move(x * x_scale, y * y_scale)
                threading.current_thread().__clock__ = None
                self.release_from_suspension()
        else:
            on_move_wrapper = None

        if on_scroll is not None:
            def on_scroll_wrapper(x, y, dx, dy):
                self.rouse_and_hold()
                threading.current_thread().__clock__ = self
                on_scroll(x * x_scale, y * y_scale, dx, dy)
                threading.current_thread().__clock__ = None
                self.release_from_suspension()
        else:
            on_scroll_wrapper = None

        # for on_press and on_release, pynput actually uses an on_click function with that takes a pressed argument
        # that seems kind of like a pain; I separate them into two different methods. I also turn button into a
        # string rather than an enum that you have to go find in the pynput package.
        if on_press is not None or on_release is not None:
            def on_click_wrapper(x, y, button, pressed):
                self.rouse_and_hold()
                threading.current_thread().__clock__ = self
                if pressed:
                    on_press(x * x_scale, y * y_scale, button.name)
                else:
                    on_release(x * x_scale, y * y_scale, button.name)
                threading.current_thread().__clock__ = None
                self.release_from_suspension()
        else:
            on_click_wrapper = None

        listener = pynput.mouse.Listener(on_move=on_move_wrapper, on_click=on_click_wrapper,
                                         on_scroll=on_scroll_wrapper, suppress=suppress, **kwargs)
        listener.start()
        self._listeners["mouse"] = listener

    def remove_mouse_listener(self):
        """
        Remove a previously added mouse listener
        """
        if "mouse" in self._listeners:
            self._listeners["mouse"].stop()
            del self._listeners["mouse"]

    # --------------------------------- Transcription Stuff -------------------------------

    def start_transcribing(self, instrument_or_instruments=None, clock=None, units="beats"):
        """
        Starts transcribing everything played in this Session's (or by the given instruments) to a Performance.
        Defaults to using this Session as the clock.

        :param instrument_or_instruments: which instruments to transcribe. Defaults to all session instruments
        :type instrument_or_instruments: ScampInstrument or list of ScampInstruments
        :param clock: which clock to record on, i.e. what are all the timings notated relative to
        :type clock: Clock
        :param units: one of ["beats", "time"]. Do we use the beats of the clock or the time?
        :type units: str

        :return: the Performance we will be transcribing to
        """
        if instrument_or_instruments is None and len(self.instruments) == 0:
            raise ValueError("Can't record with empty ensemble; did you call \"start_transcribing\" before adding "
                             "parts to the session?")

        return super().start_transcribing(
            self.instruments if instrument_or_instruments is None else instrument_or_instruments,
            self if clock is None else clock, units=units
        )

    def _to_json(self):
        json_object = Ensemble._to_json(self)
        json_object["tempo"] = self.tempo
        return json_object

    @classmethod
    def _from_json(cls, json_dict):
        json_instruments = json_dict.pop("instruments")
        default_spelling_policy = json_dict.pop("default_spelling_policy")
        session = cls(**json_dict)
        session.default_spelling_policy = default_spelling_policy
        session.instruments = [ScampInstrument._from_json(json_instrument, session)
                               for json_instrument in json_instruments]
        return session

    def __repr__(self):
        return "Session.from_json({})".format(self._to_json())
