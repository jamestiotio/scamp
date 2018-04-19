import threading
import time
import logging
from inspect import signature

from .recording_to_xml import save_to_xml_file as save_recording_to_xml

from .combined_midi_player import CombinedMidiPlayer, register_default_soundfont, \
    unregister_default_soundfont, get_default_soundfonts

from .simple_rtmidi_wrapper import get_available_midi_output_devices

from .performance import Performance, PerformancePart
from .parameter_curve import ParameterCurve

from .ensemble import Ensemble
from .instruments import PlaycorderInstrument, MidiPlaycorderInstrument

from .clock import Clock

# TODO: give the "properties" a playlength proportion, figure out how to make default playback properties of things like staccato, tenuto, slurs
# TODO: Why are there little variations in clock time?


class Playcorder:

    def __init__(self, soundfonts=None, audio_driver=None, midi_output_device=None):
        """

        :param soundfonts: the names / paths of the soundfonts this playcorder will use
        :param audio_driver: the driver used to output audio (if none, defaults to whatever fluidsynth chooses)
        :param midi_output_device: the default midi_output_device for outgoing midi streams. These can also be
        specified on a per-instrument basis, but this sets a global default. Defaults to creating virtual devices.
        """

        self._ensemble = None
        self.set_ensemble(Ensemble(soundfonts, audio_driver, midi_output_device))

        # Clock keeps track of time and can spawn subordinate clocks
        self.master_clock = Clock("MASTER")
        self._recording_clock = None
        self._recording_start_time = None

        # The Performance object created when we record
        self.performance = None

    @staticmethod
    def get_available_midi_output_devices():
        return get_available_midi_output_devices()

    @staticmethod
    def register_default_soundfont(name, soundfont_path):
        return register_default_soundfont(name, soundfont_path)

    @staticmethod
    def unregister_default_soundfont(name):
        return unregister_default_soundfont(name)

    @staticmethod
    def list_default_soundfonts():
        for a, b in get_default_soundfonts().items():
            print("{}: {}".format(a, b))

    # ----------------------------------- Clock Stuff --------------------------------

    def time(self):
        return self.master_clock.time()

    def beats(self):
        return self.master_clock.beats()

    def fork(self, process_function, name="", initial_rate=1.0):
        num_params = len(signature(process_function).parameters)
        if num_params > 1:
            logging.warning("The function passed to fork should take one argument, which is the clock used for that "
                            "thread. Additional arguments are not used.")
        elif num_params == 0:
            logging.warning("The function passed to fork must take one argument, which is the clock used for that "
                            "thread, but none were given.")
            return
        return self.master_clock.fork(process_function, name=name, initial_rate=initial_rate)

    # used for a situation where all parts are played from a single thread
    def wait(self, seconds):
        self.master_clock.wait(seconds)

    def wait_forever(self):
        while True:
            self.wait(1.0)

    # --------------------------------- Ensemble Stuff -------------------------------

    @property
    def ensemble(self):
        return self._ensemble

    @ensemble.setter
    def ensemble(self, ensemble: Ensemble):
        self.set_ensemble(ensemble)

    def set_ensemble(self, ensemble: Ensemble):
        self._ensemble = ensemble
        self._ensemble.host_playcorder = self

    def get_instruments_with_substring(self, word, avoid=None, soundfont_index=0):
        return self._ensemble.midi_player.get_instruments_with_substring(word, avoid=avoid,
                                                                         soundfont_index=soundfont_index)

    def add_part(self, instrument):
        assert isinstance(instrument, PlaycorderInstrument)
        return self._ensemble.add_part(instrument)

    def add_midi_part(self, name=None, preset=(0, 0), soundfont_index=0, num_channels=8,
                      midi_output_device=None, midi_output_name=None):
        return self._ensemble.add_midi_part(name, preset, soundfont_index, num_channels,
                                            midi_output_device, midi_output_name)

    def add_silent_part(self, name=None):
        return self._ensemble.add_silent_part(name)

    def save_ensemble_to_json(self, filepath):
        import json
        with open(filepath, "w") as file:
            json.dump(self._ensemble.to_json(), file)

    def load_ensemble_from_json(self, filepath):
        import json
        with open(filepath, "r") as file:
            self.set_ensemble(Ensemble.from_json(json.load(file)))

    # ----------------------------- Modifying MIDI Settings --------------------------

    @property
    def audio_driver(self):
        return self._ensemble.audio_driver

    @audio_driver.setter
    def audio_driver(self, audio_driver):
        self._ensemble.audio_driver = audio_driver

    @property
    def default_midi_output_device(self):
        return self._ensemble.default_midi_output_device

    @default_midi_output_device.setter
    def default_midi_output_device(self, device):
        self._ensemble.default_midi_output_device = device

    def load_soundfont(self, soundfont):
        self._ensemble.load_soundfont(soundfont)

    # --------------------------------- Recording Stuff -------------------------------

    def start_recording(self, which_parts=None, clock="absolute"):
        if isinstance(clock, str) and clock == "master":
            clock = self.master_clock
        assert clock == "absolute" or isinstance(clock, Clock)
        self._recording_clock = clock
        self._recording_start_time = self.time() if clock == "absolute" else clock.beats()
        which_parts = self._ensemble.instruments if which_parts is None else which_parts
        self.performance = Performance()
        # set a performance_part for each instrument
        for instrument in which_parts:
            new_part = self.performance.new_part(instrument)
            instrument._performance_part = new_part

    def is_recording(self):
        return self._recording_start_time is not None

    def get_recording_beat(self):
        if self._recording_clock == "absolute":
            return self.master_clock.time() - self._recording_start_time
        else:
            return self._recording_clock.beats() - self._recording_start_time

    def stop_recording(self):
        for part in self.performance.parts:
            instrument = part.instrument
            instrument.end_all_notes()
            instrument._performance_part = None
        self._recording_start_time = None
        return self.performance
