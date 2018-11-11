from xml.etree import ElementTree
from abc import ABC, abstractmethod
from fractions import Fraction
import numbers
import math
import datetime


def least_common_multiple(*args):
    # utility for getting the least_common_multiple of a list of numbers
    if len(args) == 0:
        return 1
    elif len(args) == 1:
        return args[0]
    elif len(args) == 2:
        return args[0] * args[1] // math.gcd(args[0], args[1])
    else:
        return least_common_multiple(args[0], least_common_multiple(*args[1:]))


class MusicXMLComponent(ABC):

    @abstractmethod
    def render(self):
        # Renders this component to an ElementTree.Element or a list of ElementTree.Elements
        pass

    def to_xml(self, pretty_print=False):
        element_rendering = self.render()

        if not isinstance(element_rendering, tuple):
            element_rendering = [element_rendering]
        if pretty_print:
            # this is not ideal; it's ugly and requires parsing and re-rendering and then removing version tags
            # for now, though, it's good enough and gets the desired results
            from xml.dom import minidom
            header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD ' \
                     'MusicXML 3.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
            import re
            return header + ''.join(
                re.sub(
                    "<\?xml version.*\?>\n",
                    "",
                    minidom.parseString(ElementTree.tostring(element, 'utf-8')).toprettyxml(indent="\t")
                )

                for element in element_rendering
            )
        else:
            return b''.join(ElementTree.tostring(element, 'utf-8') for element in element_rendering)

    def export_to_file(self, file_path, pretty_print=True):
        with open(file_path, 'w') as file:
            file.write(self.to_xml(pretty_print))


class Pitch(MusicXMLComponent):

    def __init__(self, step, octave, alteration=0):
        self.step = step
        self.octave = octave
        self.alteration = alteration

    @classmethod
    def from_string(cls, pitch_string: str):
        """
        Constructs Pitch from lilypond pitch string or from standard pitch octave notation
        :param pitch_string: can take the form "C#5" (specifying octave with number, and using '#' for sharp) or "cs'"
        (specifying octave in the lilypond style and using 's' for sharp)
        :return: a Pitch
        """
        pitch_string = pitch_string.lower()
        assert pitch_string[0] in ('c', 'd', 'e', 'f', 'g', 'a', 'b'), "Pitch string not understood"
        step = pitch_string[0].upper()
        if pitch_string[1:].startswith(('b', 'f', '#', 's')):
            alteration = -1 if pitch_string[1:].startswith(('b', 'f')) else 1
            octave_string = pitch_string[2:]
        elif pitch_string[1:].startswith(('qb', 'qf', 'q#', 'qs')):
            alteration = -0.5 if pitch_string[1:].startswith(('qb', 'qf')) else 0.5
            octave_string = pitch_string[3:]
        else:
            alteration = 0
            octave_string = pitch_string[1:]

        try:
            octave = int(octave_string)
        except ValueError:
            if all(x == '\'' for x in octave_string):
                octave = 3 + len(octave_string)
            elif all(x == ',' for x in octave_string):
                octave = 3 - len(octave_string)
            else:
                raise ValueError("Pitch string not understood")
        return cls(step, octave, alteration)

    def render(self):
        element = ElementTree.Element("pitch")
        step_el = ElementTree.Element("step")
        step_el.text = self.step
        alter_el = ElementTree.Element("alter")
        alter_el.text = str(self.alteration)
        octave_el = ElementTree.Element("octave")
        octave_el.text = str(self.octave)
        element.append(step_el)
        element.append(alter_el)
        element.append(octave_el)
        return element

    def __repr__(self):
        return "Pitch(\"{}\", {}{})".format(self.step, self.octave,
                                        ", {}".format(self.alteration) if self.alteration != 0 else "")


class Duration(MusicXMLComponent):

    length_to_note_type = {
        8.0: "breve",
        4.0: "whole",
        2.0: "half",
        1.0: "quarter",
        0.5: "eighth",
        0.25: "16th",
        1.0 / 8: "32nd",
        1.0 / 16: "64th",
        1.0 / 32: "128th",
        1.0 / 64: "256th",
        1.0 / 128: "512th",
        1.0 / 256: "1024th"
    }

    note_type_to_length = {b: a for a, b in length_to_note_type.items()}

    valid_divisors = tuple(4 / x for x in length_to_note_type)

    note_type_to_num_beams = {
        "breve": 0,
        "whole": 0,
        "half": 0,
        "quarter": 0,
        "eighth": 1,
        "16th": 2,
        "32nd:": 3,
        "64th": 4,
        "128th": 5,
        "256th": 6,
        "512th": 7,
        "1024th": 8
    }

    def __init__(self, note_type, num_dots=0, tuplet_ratio=None):
        """
        Represents a length that can be written as a single note or rest.
        :param note_type: written musicXML duration type, e.g. quarter
        :param num_dots: self-explanatory
        :param tuplet_ratio: a tuple of either (# actual notes, # normal notes) or (# actual, # normal, note type),
        e.g. (4, 3, 0.5) for 4 in the space of 3 eighths.
        """
        assert note_type in Duration.length_to_note_type.values()
        self.note_type = note_type
        self.num_dots = num_dots
        assert isinstance(tuplet_ratio, (type(None), tuple))
        self.tuplet_ratio = tuplet_ratio

        self.divisions = Fraction(self.true_length).limit_denominator().denominator

    @staticmethod
    def _dot_multiplier(num_dots):
        return (2.0 ** (num_dots + 1) - 1) / 2.0 ** num_dots

    @property
    def written_length(self):
        return Duration.note_type_to_length[self.note_type] * Duration._dot_multiplier(self.num_dots)

    @property
    def true_length(self):
        # length taking into account tuplet time modification
        tuplet_modification = 1 if self.tuplet_ratio is None else float(self.tuplet_ratio[1]) / self.tuplet_ratio[0]
        return self.written_length * tuplet_modification

    def num_beams(self):
        return Duration.note_type_to_num_beams[self.note_type]

    @classmethod
    def from_written_length(cls, written_length, tuplet_ratio=None, max_dots_allowed=4):
        try:
            note_type, num_dots = Duration.get_note_type_and_number_of_dots(written_length, max_dots_allowed)
        except ValueError as err:
            raise err

        tuplet_ratio = tuplet_ratio

        return cls(note_type, num_dots, tuplet_ratio)

    @classmethod
    def from_divisor(cls, divisor, num_dots=0, tuplet_ratio=None):
        assert isinstance(divisor, int) and (4.0 / divisor) in Duration.length_to_note_type, "Bad divisor"
        return cls.from_written_length(4.0 / divisor * Duration._dot_multiplier(num_dots), tuplet_ratio=tuplet_ratio)

    @classmethod
    def from_string(cls, duration_string: str):
        if duration_string in Duration.note_type_to_length:
            return cls(duration_string)
        elif duration_string.startswith("dotted "):
            assert duration_string[7:] in Duration.note_type_to_length
            return cls(duration_string[7:], 1)

        num_dots = 0
        while duration_string.endswith('.'):
            duration_string = duration_string[:-1]
            num_dots += 1
        try:
            divisor = int(duration_string)
            assert divisor in Duration.valid_divisors
        except (ValueError, AssertionError):
            raise ValueError("Bad duration string.")
        return cls.from_divisor(divisor, num_dots=num_dots)

    @staticmethod
    def get_note_type_and_number_of_dots(length, max_dots_allowed=4):
        if length in Duration.length_to_note_type:
            return Duration.length_to_note_type[length], 0
        else:
            dots_multiplier = 1.5
            dots = 1
            while length / dots_multiplier not in Duration.length_to_note_type:
                dots += 1
                dots_multiplier = (2.0 ** (dots + 1) - 1) / 2.0 ** dots
                if dots > max_dots_allowed:
                    raise ValueError("Duration length of {} does not resolve to single note type.".format(length))
            return Duration.length_to_note_type[length / dots_multiplier], dots

    def render(self):
        elements = []
        # specify all the duration-related attributes
        duration_el = ElementTree.Element("duration")
        duration_el.text = str(int(round(self.true_length * self.divisions)))
        elements.append(duration_el)

        type_el = ElementTree.Element("type")
        type_el.text = self.note_type
        elements.append(type_el)

        for _ in range(self.num_dots):
            elements.append(ElementTree.Element("dot"))

        if self.tuplet_ratio is not None:
            time_modification = ElementTree.Element("time-modification")
            ElementTree.SubElement(time_modification, "actual-notes").text = str(self.tuplet_ratio[0])
            ElementTree.SubElement(time_modification, "normal-notes").text = str(self.tuplet_ratio[1])
            if len(self.tuplet_ratio) > 2:
                if self.tuplet_ratio[2] not in Duration.length_to_note_type:
                    raise ValueError("Tuplet normal note type is not a standard power of two length.")
                ElementTree.SubElement(time_modification, "normal-type").text = \
                    Duration.length_to_note_type[self.tuplet_ratio[2]]
            elements.append(time_modification)
        return elements

    def __repr__(self):
        return "Duration(\"{}\", {}{})".format(self.note_type, self.num_dots,
                                           ", {}".format(self.tuplet_ratio) if self.tuplet_ratio is not None else "")


class _XMLNote(MusicXMLComponent):

    def __init__(self, pitch, duration, ties=None, notations=(), articulations=(), notehead=None, beams=None,
                 is_chord_member=False, voice=None, staff=None):
        """
        Implementation for the xml note element, which includes notes and rests
        :param pitch: a Pitch, or None to indicate a rest, or "bar rest" to indicate that it's a bar rest
        :param duration: a Duration, or just a float representing the bar length in quarter in the case of "bar rest"
        :param ties: "start", "continue", "stop", or None
        :param notations: list for contents of the musicXML "notations" tag
        :param articulations: list of articulations to go in the musicXML "articulations" tag (itself in "notations")
        :param notehead: str representing XML notehead type
        :param beams: a dict of { beam_level (int): beam_type } where beam type is one of ("begin", "continue", "end",
        "forward hook", "backward hook")
        :param is_chord_member: boolean for whether this is a secondary member of a chord (in which case it contains
        the <chord /> tag
        :param voice: which voice this note belongs to within its given staff
        :param staff: which staff this note belongs to within its given part
        """
        self.pitch = pitch
        self.duration = duration
        self.divisions = self.min_denominator()
        assert ties in ("start", "continue", "stop", None)
        self.ties = ties
        self.notations = list(notations) if not isinstance(notations, list) else notations
        self.articulations = list(articulations) if not isinstance(articulations, list) else articulations
        self.tuplet_bracket = None
        self.notehead = notehead
        self.beams = {} if beams is None else beams
        self.is_chord_member = is_chord_member
        self.voice = voice
        self.staff = staff

    def render(self):
        element = ElementTree.Element("note")

        # ------------ set pitch and duration attributes ------------

        if self.pitch == "bar rest":
            # bar rest; in this case the duration is just a float, since it looks like a whole note regardless
            element.append(ElementTree.Element("rest"))
            duration_el = ElementTree.Element("duration")
            duration_el.text = str(int(round(self.duration * self.divisions)))
            element.append(duration_el)
            # # old version: Seems to produce non-ideal results in musescore
            # element.append(ElementTree.Element("rest", {"measure": "yes"}))
            # duration_el = ElementTree.Element("duration")
            # duration_el.text = str(int(round(self.duration * self.divisions)))
            # element.append(duration_el)
            # type_el = ElementTree.Element("type")
            # type_el.text = "whole"
            # element.append(type_el)

        else:
            # a note or rest with explicit written duration
            if self.pitch is None:
                # normal rest
                element.append(ElementTree.Element("rest"))
            else:
                # pitched note
                assert isinstance(self.pitch, Pitch)

                if self.is_chord_member:
                    element.append(ElementTree.Element("chord"))
                element.append(self.pitch.render())

            assert isinstance(self.duration, Duration)
            self.duration.divisions = self.divisions
            element.extend(self.duration.render())

        # ------------------ set voice and staff ----------------

        if self.voice is not None:
            voice_el = ElementTree.Element("voice")
            voice_el.text = str(self.voice)
            element.append(voice_el)

        if self.staff is not None:
            staff_el = ElementTree.Element("staff")
            staff_el.text = str(self.staff)
            element.append(staff_el)

        # ---------------- set attributes that apply to notes only ----------------

        if self.pitch is not None:
            if self.notehead is not None:
                element.append(self.notehead)
            if self.ties is not None:
                if self.ties.lower() == "start" or self.ties.lower() == "continue":
                    element.append(ElementTree.Element("tie", {"type": "start"}))
                    self.notations.append(ElementTree.Element("tied", {"type": "start"}))
                if self.ties.lower() == "stop" or self.ties.lower() == "continue":
                    element.append(ElementTree.Element("tie", {"type": "stop"}))
                    self.notations.append(ElementTree.Element("tied", {"type": "stop"}))
            for beam_num in self.beams:
                beam_text = self.beams[beam_num]
                beam_el = ElementTree.Element("beam", {"number": str(beam_num)})
                beam_el.text = beam_text
                element.append(beam_el)

        # ------------------ add any notations and articulations ----------------

        if len(self.notations) + len(self.articulations) > 0:
            # there is either a notation or an articulation, so we'll add a notations tag
            notations_el = ElementTree.Element("notations")
            for notation in self.notations:
                if isinstance(notation, ElementTree.Element):
                    notations_el.append(notation)
                else:
                    notations_el.append(ElementTree.Element(notation))

            if self.tuplet_bracket in ("start", "both"):
                notations_el.append(ElementTree.Element("tuplet", {"type": "start"}))
            if self.tuplet_bracket in ("stop", "both"):
                notations_el.append(ElementTree.Element("tuplet", {"type": "stop"}))

            if len(self.articulations) > 0:
                articulations_el = ElementTree.SubElement(notations_el, "articulations")
                for articulation in self.articulations:
                    if isinstance(articulation, ElementTree.Element):
                        articulations_el.append(articulation)
                    else:
                        articulations_el.append(ElementTree.Element(articulation))
            element.append(notations_el)

        return element

    @property
    def true_length(self):
        return self.duration.true_length if isinstance(self.duration, Duration) else self.duration

    @property
    def written_length(self):
        return self.duration.written_length if isinstance(self.duration, Duration) else self.duration

    def min_denominator(self):
        if isinstance(self.duration, Duration):
            return Fraction(self.duration.true_length).limit_denominator().denominator
        else:
            return Fraction(self.duration).limit_denominator().denominator

    def num_beams(self):
        return 0 if self.pitch is None else self.duration.num_beams()


class Note(_XMLNote):

    def __init__(self, pitch, duration, ties=None, notations=(), articulations=(), notehead=None):
        if isinstance(pitch, str):
            pitch = Pitch.from_string(pitch)
        assert isinstance(pitch, Pitch)

        if isinstance(duration, str):
            duration = Duration.from_string(duration)
        elif isinstance(duration, numbers.Number):
            duration = Duration.from_written_length(duration)

        assert ties in ("start", "continue", "stop", None)

        assert isinstance(duration, Duration)
        super().__init__(pitch, duration, ties=ties, notations=notations,
                         articulations=articulations, notehead=notehead)

    def __repr__(self):
        return "Note({}, {}{}{}{}{})".format(
            self.pitch, self.duration,
            ", ties=\"{}\"".format(self.ties) if self.ties is not None else "",
            ", notations={}".format(self.notations) if len(self.notations) > 0 else "",
            ", articulations={}".format(self.articulations) if len(self.articulations) > 0 else "",
            ", notehead=\"{}\"".format(self.notehead) if self.notehead is not None else ""
        )


class Rest(_XMLNote):

    def __init__(self, duration, notations=()):
        if isinstance(duration, str):
            duration = Duration.from_string(duration)
        elif isinstance(duration, numbers.Number):
            duration = Duration.from_written_length(duration)

        assert isinstance(duration, Duration)
        super().__init__(None, duration, notations=notations)

    def __repr__(self):
        return "Rest({}{})".format(
            self.duration,
            ", notations={}".format(self.notations) if len(self.notations) > 0 else ""
        )


class BarRest(_XMLNote):

    def __init__(self, bar_length):
        if isinstance(bar_length, Duration):
            bar_length = Duration.true_length
        super().__init__("bar rest", bar_length)


class Chord(MusicXMLComponent):

    def __init__(self, pitches, duration, ties=None, notations=(), articulations=(), noteheads=None):
        assert isinstance(pitches, (list, tuple)) and len(pitches) > 1, "Chord should have multiple notes."
        pitches = [Pitch.from_string(pitch) if isinstance(pitch, str) else pitch for pitch in pitches]
        assert all(isinstance(pitch, Pitch) for pitch in pitches)

        if isinstance(duration, str):
            duration = Duration.from_string(duration)
        elif isinstance(duration, numbers.Number):
            duration = Duration.from_written_length(duration)
        assert isinstance(duration, Duration)

        assert ties in ("start", "continue", "stop", None) or \
               isinstance(ties, (list, tuple)) and len(ties) == len(pitches) and \
               all(x in ("start", "continue", "stop", None) for x in ties)

        self.notes = tuple(
            Note(pitch, duration,
                 ties=ties if not isinstance(ties, (list, tuple)) else ties[i],
                 notations=notations if i == 0 else (),
                 articulations=articulations if i == 0 else (),
                 notehead=noteheads[i] if noteheads is not None else None)
            for i, pitch in enumerate(pitches)
        )

        for note in self.notes[1:]:
            note.is_chord_member = True

    def num_beams(self):
        return self.notes[0].num_beams()

    @property
    def true_length(self):
        return self.notes[0].true_length

    @property
    def written_length(self):
        return self.notes[0].written_length

    @property
    def notations(self):
        return self.notes[0].notations

    @property
    def articulations(self):
        return self.notes[0].articulations

    @property
    def divisions(self):
        return self.notes[0].divisions

    @divisions.setter
    def divisions(self, value):
        for note in self.notes:
            note.divisions = value

    @property
    def beams(self):
        # beams are only written into the first note of a chord so we make an alias to that
        return self.notes[0].beams

    @beams.setter
    def beams(self, value):
        self.notes[0].beams = value

    @property
    def ties(self):
        # either returns a string representing the tie state of all the notes, if all notes have the same tie state
        # or returns a tuple representing the tie state of each note individually
        if all(note.ties == self.notes[0].ties for note in self.notes[1:]):
            return self.notes[0].ties
        else:
            return tuple(note.ties for note in self.notes)

    @ties.setter
    def ties(self, value):
        if isinstance(value, (list, tuple)):
            assert len(value) == len(self.notes)
            for i, note in enumerate(self.notes):
                note.ties = value[i]
        else:
            assert value in ("start", "continue", "stop", None)
            for note in self.notes:
                note.ties = value

    def min_denominator(self):
        return self.notes[0].min_denominator()

    def render(self):
        return tuple(note.render() for note in self.notes)


class BeamedGroup(MusicXMLComponent):

    def __init__(self, contents):
        assert hasattr(contents, '__len__') and all(isinstance(x, (Note, Chord, Rest)) for x in contents)
        self.contents = contents

    def render_contents_beaming(self):
        for beam_depth in range(1, max(leaf.num_beams() for leaf in self.contents) + 1):
            leaf_start_time = 0
            for i, leaf in enumerate(self.contents):
                last_note_active = i > 0 and self.contents[i-1].num_beams() >= beam_depth
                this_note_active = leaf.num_beams() >= beam_depth
                next_note_active = i < len(self.contents) - 1 and self.contents[i+1].num_beams() >= beam_depth

                if this_note_active:
                    if last_note_active and next_note_active:
                        leaf.beams[beam_depth] = "continue"
                    elif last_note_active:
                        leaf.beams[beam_depth] = "end"
                    elif next_note_active:
                        leaf.beams[beam_depth] = "begin"
                    else:
                        if int(round(leaf_start_time / 0.5 ** beam_depth)) % 2 == 0:
                            leaf.beams[beam_depth] = "forward hook"
                        else:
                            leaf.beams[beam_depth] = "backward hook"

                leaf_start_time += leaf.written_length

        for leaf in self.contents:
            if all("hook" in beam_value for beam_value in leaf.beams.values()):
                leaf.beams = {}

    @property
    def divisions(self):
        return self.contents[0].divisions

    @divisions.setter
    def divisions(self, value):
        for leaf in self.contents:
            leaf.divisions = value

    def min_denominator(self):
        return least_common_multiple(*[n.min_denominator() for n in self.contents])

    def render(self):
        self.render_contents_beaming()
        rendered_notes = []
        for leaf in self.contents:
            rendered_leaf = leaf.render()
            if isinstance(rendered_leaf, tuple):
                rendered_notes.extend(rendered_leaf)
            else:
                rendered_notes.append(rendered_leaf)
        return tuple(rendered_notes)


class Tuplet(BeamedGroup):

    def __init__(self, contents, ratio):
        super().__init__(contents)
        self.ratio = ratio
        self.set_tuplet_info_for_contents(ratio)

    def set_tuplet_info_for_contents(self, ratio):
        self.contents[0].tuplet_bracket = "start"
        # it would be stupid to have a tuplet that has only one note in it, but we'll cover that case anyway
        self.contents[-1].tuplet_bracket = "stop" if len(self.contents) > 0 else "both"

        for element in self.contents:
            if isinstance(element, Chord):
                for note in element.notes:
                    note.duration.tuplet_ratio = ratio
            else:
                element.duration.tuplet_ratio = ratio

    def min_denominator(self):
        self.set_tuplet_info_for_contents(self.ratio)
        return least_common_multiple(*[n.min_denominator() for n in self.contents])

    def render(self):
        self.set_tuplet_info_for_contents(self.ratio)
        return super().render()


clef_name_to_letter_and_line = {
    "treble": ("G", 2),
    "bass": ("F", 4),
    "alto": ("C", 3),
    "tenor": ("C", 4)
}


class Measure(MusicXMLComponent):

    barline_name_to_xml_name = {
        "double": "light-light",
        "end": "light-heavy",
    }

    def __init__(self, contents, time_signature=None, clef=None, barline=None, staves=None, number=1):
        assert hasattr(contents, '__len__') and \
               all(isinstance(x, (Note, Rest, Chord, BarRest, BeamedGroup, Tuplet)) for x in contents)
        self.contents = contents
        self.number = number
        self.time_signature = time_signature
        self.clef = clef
        self.barline = barline
        self.staves = staves

    def leaves(self):
        out = []
        for note_or_tuplet in self.contents:
            if isinstance(note_or_tuplet, Tuplet):
                out.extend(note_or_tuplet.contents)
            else:
                out.append(note_or_tuplet)
        return out

    def render(self):
        element = ElementTree.Element("measure", {"number": str(self.number)})

        attributes_el = ElementTree.SubElement(element, "attributes")

        num_beat_divisions = least_common_multiple(*[x.min_denominator() for x in self.leaves()])
        for note in self.leaves():
            note.divisions = num_beat_divisions

        divisions_el = ElementTree.SubElement(attributes_el, "divisions")
        divisions_el.text = str(num_beat_divisions)

        if self.time_signature is not None:
            # time_signature is expressed as a tuple
            assert isinstance(self.time_signature, tuple) and len(self.time_signature) == 2
            time_el = ElementTree.SubElement(attributes_el, "time")
            ElementTree.SubElement(time_el, "beats").text = str(self.time_signature[0])
            ElementTree.SubElement(time_el, "beat-type").text = str(self.time_signature[1])

        if self.clef is not None:
            # clef is a tuple: the first element is the sign ("G" clef of "F" clef)
            # the second element is the line the sign centers on
            # an optional third element expresses the number of octaves transposition up or down
            # however, we also take words like "treble" and convert them
            if self.clef in clef_name_to_letter_and_line:
                self.clef = clef_name_to_letter_and_line[self.clef]
            clef_el = ElementTree.SubElement(attributes_el, "clef")
            ElementTree.SubElement(clef_el, "sign").text = self.clef[0]
            ElementTree.SubElement(clef_el, "line").text = str(self.clef[1])
            if len(self.clef) > 2:
                ElementTree.SubElement(clef_el, "clef-octave-change").text = str(self.clef[2])

        if self.staves is not None:
            staves_el = ElementTree.SubElement(attributes_el, "staves")
            staves_el.text = str(self.staves)

        for note_or_tuplet in self.contents:
            rendered_content = note_or_tuplet.render()
            if isinstance(rendered_content, tuple):
                element.extend(rendered_content)
            else:
                element.append(rendered_content)

        if self.barline is not None:
            barline_el = ElementTree.Element("barline", {"location": "right"})
            element.append(barline_el)
            if self.barline in Measure.barline_name_to_xml_name:
                self.barline = Measure.barline_name_to_xml_name[self.barline]
            ElementTree.SubElement(barline_el, "bar-style").text = self.barline
        return element


class Part(MusicXMLComponent):

    def __init__(self, part_name, measures, part_id=1):
        self.part_id = part_id
        assert hasattr(measures, '__len__') and all(isinstance(x, Measure) for x in measures)
        self.measures = measures
        self.part_name = part_name

    def render(self):
        element = ElementTree.Element("part", {"id": "P{}".format(self.part_id)})
        for i, measure in enumerate(self.measures):
            measure.number = i + 1
            element.append(measure.render())
        return element

    def render_part_list_entry(self):
        score_part_el = ElementTree.Element("score-part", {"id": "P{}".format(self.part_id)})
        ElementTree.SubElement(score_part_el, "part-name").text = self.part_name
        return score_part_el


class PartGroup:

    def __init__(self, parts, has_bracket=True, has_group_bar_line=True):
        assert hasattr(parts, '__len__') and all(isinstance(x, Part) for x in parts)
        self.parts = parts
        self.has_bracket = has_bracket
        self.has_group_bar_line = has_group_bar_line

    def render(self):
        return tuple(part.render() for part in self.parts)

    def render_part_list_entry(self):
        return (self.render_start_element(), ) + \
               tuple(part.render_part_list_entry() for part in self.parts) + \
               (self.render_stop_element(), )

    def render_start_element(self):
        start_element = ElementTree.Element("part-group", {"type": "start"})
        if self.has_bracket:
            ElementTree.SubElement(start_element, "group-symbol").text = "bracket"
        ElementTree.SubElement(start_element, "group-barline").text = "yes" if self.has_group_bar_line else "no"
        return start_element

    @staticmethod
    def render_stop_element():
        return ElementTree.Element("part-group", {"type": "stop"})


class Score(MusicXMLComponent):

    def __init__(self, parts, title=None, composer=None):
        assert hasattr(parts, '__len__') and all(isinstance(x, (Part, PartGroup)) for x in parts)
        self.parts = parts
        self.title = title
        self.composer = composer

    def set_part_numbers(self):
        next_id = 1
        for part_or_group in self.parts:
            if isinstance(part_or_group, PartGroup):
                for part in part_or_group.parts:
                    part.part_id = next_id
                    next_id += 1
            else:
                part_or_group.part_id = next_id
                next_id += 1

    def render(self):
        self.set_part_numbers()
        score_element = ElementTree.Element("score-partwise")
        work_el = ElementTree.SubElement(score_element, "work")
        if self.title is not None:
            ElementTree.SubElement(work_el, "work-title").text = self.title
        id_el = ElementTree.SubElement(score_element,"identification")
        if self.composer is not None:
            ElementTree.SubElement(id_el, "creator", {"type": "composer"}).text = self.composer
        encoding_el = ElementTree.SubElement(id_el, "encoding")
        ElementTree.SubElement(encoding_el, "encoding-date").text = str(datetime.date.today())
        ElementTree.SubElement(encoding_el, "software").text = "SCAMP (Suite for Composing Algorithmic Music in Python)"
        part_list_el = ElementTree.SubElement(score_element, "part-list")
        for part in self.parts:
            if isinstance(part, PartGroup):
                part_list_el.extend(part.render_part_list_entry())
                score_element.extend(part.render())
            else:
                part_list_el.append(part.render_part_list_entry())
                score_element.append(part.render())
        return score_element

# # ------------------- A SHORT EXAMPLE --------------------
#
# Score([
#     PartGroup([
#         Part("Oboe", [
#             Measure([
#                 Note("d5", 1.5),
#                 BeamedGroup([
#                     Note("f#4", 0.25),
#                     Note("A#4", 0.25)
#                 ]),
#                 Chord(["Cs4", "Ab4"], 1.0),
#                 Rest(1.0)
#             ], time_signature=(4, 4)),
#             Measure([
#                 Tuplet([
#                     Note("c5", 0.5),
#                     Note("bb4", 0.25),
#                     Note("a4", 0.25),
#                     Note("b4", 0.25),
#                 ], (5, 4)),
#                 Note("f4", 2),
#                 Rest(1)
#             ], barline="end")
#         ]),
#         Part("Clarinet", [
#             Measure([
#                 Tuplet([
#                     Note("c5", 0.5),
#                     Note("bb4", 0.25),
#                     Note("a4", 0.25),
#                     Note("b4", 0.25),
#                 ], (5, 4)),
#                 Note("f4", 2),
#                 Rest(1)
#             ], time_signature=(4, 4)),
#             Measure([
#                 Note("d5", 1.5),
#                 BeamedGroup([
#                     Note("f#4", 0.25),
#                     Note("A#4", 0.25)
#                 ]),
#                 Chord(["Cs4", "Ab4"], 1.0),
#                 Rest(1.0)
#             ], barline="end")
#         ])
#     ]),
#     Part("Bassoon", [
#         Measure([
#             BarRest(4)
#         ], time_signature=(4, 4), clef="bass"),
#         Measure([
#             Rest(1.0),
#             Note("c4", 2.0),
#             Note("Eb3", 0.5),
#             Rest(0.5)
#         ], barline="end")
#     ])
# ], title="MusicXML Example", composer="Beethoven").export_to_file("Example.xml")
