"""
    Copyright Ryan Kirkbride 2015

    This module contains the objects for Instrument Players (those that send musical
    information to SuperCollider) and Sample Players (those that send buffer IDs to
    playback specific samples located in the Samples directory).

"""

from os.path import dirname
from random import shuffle

from SCLang import SynthDefProxy
from Patterns import *
from Midi import *

import Code
import Buffers

BufferManager = Buffers.BufferManager().from_file()

#### Methods

class MethodCall:
    def __init__(self, player, method, n, args=()):
        self.player = player
        self.name = method
        self.when = asStream(n)
        self.i    = 0
        self.next = self.when[self.i]
        t = self.player.metro.now()
        self.next = (t - (t % self.player.metro.ts[0])) + self.next
        self.args = args
    def __call__(self):
        self.i += 1
        self.next += modi(self.when, self.i)
        if type(self.args) is tuple:
            args = [modi(arg, self.i) for arg in self.args]
        else:
            args = [modi(self.args, self.i)]
        getattr(self.player, self.name).__call__(*args)    
        

##################### ROOT PLAYER OBJECT #####################

SamplePlayer = 'play'

class PlayerObject(Code.LiveObject):

    _VARS = []
    _INIT = False

    metro = None
    server = None

    def __init__( self, name ):

        self.name     = name
        
        self.SynthDef = None
        self.quantise = False
        self.stopping = False
        self.stop_point = 0
        self.following = None

        # Modifiers
        
        self.reversing = False
        self.when_statements = []

        # Keeps track of echo effects

        self.echo_on = False
        self.echo_fx = {}

        # Keeps track of which note to play etc

        self.event_index = 0
        self.event_n = 0
        self.notes_played = 0
        self.event = {}

        # Used for checking clock updates
        
        self.old_dur = None
        self.isplaying = False
        self.isAlive = True
        self.last_offset = 0

        # These dicts contain the attribute and modifier values that are sent to SuperCollider

        self.attr = {}
        self.modf = {}

        # Hold a list of any schedule methods

        self.scheduled_events = {}
        
        # List the internal variables we don't want to send to SuperCollider

        self._VARS = self.__dict__.keys()

        # Default attribute dictionary

        self.dur    = self.attr['dur']      =  [0]
        self.degree = self.attr['degree']   =  [0]
        self.oct    = self.attr['oct']      =  [5]
        self.amp    = self.attr['amp']      =  [1]
        self.pan    = self.attr['pan']      =  [0]
        self.sus    = self.attr['sus']      =  [1]
        self.rate   = self.attr['rate']     =  [1]
        self.buf    = self.attr['buf']      =  [0]
        self.echo   = self.attr['echo']     =  [0]
        self.offset = self.attr['offset']   =  [0]
        #self.bpm = ...
        self.freq   = [0]

        self.reset()

    """ The PlayerObject Method >> """

    def __rshift__(self, other):
        # Player Object Manipulation
        if isinstance(other, SynthDefProxy):
            self.update(other.name, other.degree, **other.kwargs)
            self + other.mod
            for method, arguments in other.methods.items():
                args, kwargs = arguments
                getattr(self, method).__call__(*args, **kwargs)                
            return self
        raise TypeError("{} is an innapropriate argument type for PlayerObject".format(other))
        return self

    def __setattr__(self, name, value):
        if self._INIT:
            if name not in self._VARS:
                value = asStream(value)
                self.attr[name] = value
        self.__dict__[name] = value
        return

    # --- Startup methods

    def reset(self):
        self.modf = dict([(key, [0]) for key in self.attr])
        self.modf['amp'] = 0.5
        return self    

    # --- Update methods

    def __call__(self):

        if self.stopping and self.metro.now() >= self.stop_point:
            self.kill()
            return

        if self.dur_updated():

            self.event_n, self.event_index = self.count()
        
        # Get the current state

        self.get_event()

        # Get next occurence

        dur = float(self.event['dur'])

        offset = float(self.event["offset"]) - self.last_offset

        # Schedule the next event

        self.event_index = self.event_index + dur + offset
        
        self.metro.schedule(self, self.event_index)

        # Store any offset

        self.last_offset = self.event["offset"]

        # Change internal marker

        self.event_n += 1 if not self.reversing else -1
        self.notes_played += 1

        # Call any player methods

        for cmd in self.scheduled_events.values():

            # Call the MethodCall
            
            if self.event_index >= cmd.next: cmd()

        # Play the note

        if self.metro.solo is None or self.metro.solo is self:

            self.freq = 0 if self.SynthDef is SamplePlayer else self.calculate_freq()

            self.send()

        return

    def count(self):

        # Count the events that should have taken place between 0 and now()

        n = 0
        acc = 0
        dur = 0
        now = self.metro.now()

        durations = self.rhythm()
        total_dur = sum(durations)

        if total_dur == 0:

            print "Warning: Player object has a total duration of 0. Set to 1"
            self.dur=total_dur=durations=1
    
        acc = now - (now % total_dur)

        while True:
            
            dur = float(modi(durations, n))

            if acc + dur > now:

                break

            else:
                
                acc += dur
                n += 1

        # Store duration times

        self.old_dur = self.attr['dur']

        # Returns value for self.event_n and self.event_index

        self.notes_played = n

        return n, acc

    def update(self, synthdef, degree, **kwargs):
        
        if self.isplaying is False:

            # Add to clock        
            self.isplaying = True
            self.event_index = self.metro.NextBar()
            self.event_n = 0
            self.metro.schedule(self, self.event_index)

        setattr(self, "SynthDef", synthdef)

        if not self._INIT:

            if synthdef is SamplePlayer: 

                self.dur = self.attr['dur'] = asStream(0.5)
                self.old_pattern_dur = self.dur

            else:

                self.scale = kwargs.get("scale", PlayerObject.default_scale )
                self.root = self.attr['root']  = asStream(kwargs.get( "root",  PlayerObject.default_root ))
                self.dur  = self.attr['dur']   = asStream(1)
                self.sus  = self.attr['sus']   = asStream(1)

        # Finish init (any assigned attributes now go in the player.attr dict

        if not self._INIT: self._INIT = True

        # Update the attribute value

        for name, value in kwargs.items():

            if self.SynthDef == 'bass': print name, value

            setattr(self, name, value)

        # Set the degree and update sustain to equal duration if not specified

        if synthdef is SamplePlayer:

            setattr(self, "degree", str(degree) if len(degree) > 0 else " ")

        else:

            setattr(self, "degree", degree)

            if 'sus' not in kwargs:

                setattr(self, 'sus', self.dur)

        return self

    def dur_updated(self):
        dur_updated = self.attr['dur'] != self.old_dur
        if self.SynthDef == SamplePlayer:
            dur_updated = (self.pattern_rhythm_updated() or dur_updated)
        return dur_updated
    

    def rhythm(self):
        r = asStream(self.attr['dur'])
        if self.SynthDef is SamplePlayer:
            r = r * [char.dur for char in self.attr['degree'].flat()]
        return r

    def pattern_rhythm_updated(self):
        r = self.rhythm()
        if self.old_pattern_dur != r:
            self.old_pattern_dur = r
            return True
        return False

    def char(self, other=None):
        if other is not None:
            try:
                if type(other) == str and len(other) == 1: #char
                    return BufferManager.bufnum(self.now('buf')) == other
                raise TypeError("Argument should be a one character string")
            except:
                return False
        else:
            try:
                return BufferManager.bufnum(self.now('buf'))
            except:
                return None

    def calculate_freq(self):
        """ Uses the scale, octave, and degree to calculate the frequency values to send to SuperCollider """

        now = {}
        
        for attr in ('degree', 'oct'):

            now[attr] = self.event[attr]

            try:

                now[attr] = list(now[attr])

            except:

                now[attr] = [now[attr]]
                
        size = max( len(now['oct']), len(now['degree']) )

        f = []

        for i in range(size):

            try:
                
                midinum = midi( self.scale, modi(now['oct'], i), modi(now['degree'], i) , self.now('root') )

            except:

                print self.event
                raise

            f.append( miditofreq(midinum) )
            
        return f

    def f(self, data):

        """ adds value to frequency modifier """

        if type(data) == int:

            data = [data]

        # Add to modulator

        self.modf['freq'] = circular_add(self.modf['freq'], data)

        return self

    # Methods affecting other players - every n times, do a random thing?

    def stutter(self, n=2):
        """ repeats each value in each stream n times """

        # if n is a list, stutter each degree[i] by n[i] times

        self.degree = PStutter(self.degree, n)

        return self

    def __int__(self):
        return int(self.now('degree'))

    def __float__(self):
        return float(self.now('degree'))

    def __add__(self, data):
        """ Change the degree modifier stream """
        self.modf['degree'] = asStream(data)
        return self

    def __iadd__(self, data):
        """ Increment the degree modifier stream """
        self.modf['degree'] = circular_add(self.modf['degree'], asStream(data))
        return self

    def __sub__(self, data):
        """ Change the degree modifier stream """
        data = asStream(data)
        data = [d * -1 for d in data]
        self.modf['degree'] = data
        return self

    def __isub__(self, data):
        """ de-increment the modifier stream """
        data = asStream(data)
        data = [d * -1 for d in data]
        self.modf['degree'] = circular_add(self.modf['degree'], data)
        return self

    def __mul__(self, data):

        """ Multiplying an instrument player multiplies each amp value by
            the input, or circularly if the input is a list. The input is
            stored here and calculated at the update stage """

        if type(data) in (int, float):

            data = [data]

        self.modf['amp'] = asStream(data)

        return self

    def __div__(self, data):

        if type(data) in (int, float):

            data = [data]

        self.modf['amp'] = [1.0 / d for d in data]

        return self

    # --- Data methods

    def tupleN(self):
        """ Returns the length of the largest nested tuple in the attr dict """

        exclude = 'degree' if self.SynthDef is SamplePlayer else None

        size = len(self.freq)
        
        for attr, value in self.event.items():
            if attr != exclude:
                try:
                    l = len(value)
                    if l > size:
                        size = l
                except:
                    pass

        return size

    # --- Methods for preparing and sending OSC messages to SuperCollider

    def now(self, attr="degree", x=0):
        """ Calculates the values for each attr to send to the server at the current clock time """

        modifier_event_n = self.event_n

        # Get which instrument is leading

        if self.following and attr == 'degree':

            attr_value = self.following.now('degree')
            
        else:
    
            attr_value = modi(self.attr[attr], self.event_n + x)
        
        # If the attribute isn't in the modf dictionary, default to 0

        try:

            modf_value = modi(self.modf[attr], modifier_event_n + x)

        except:

            modf_value = 0

        # If any values are time-dependant, get the now values

        try:

            attr_value = attr_value.now()

        except:

            pass

        try:

            modf_value = modf_value.now()

        except:

            pass

        # Combine attribute and modifier values

        try:

            # Amp is multiplied, not added

            if attr == "amp":

                value = attr_value * modf_value

            else:
            
                value = attr_value + modf_value

        except:

            value = attr_value
            
        return value

    def get_event(self):
        """ Returns a dictionary of attr -> now values """

        if self.SynthDef is SamplePlayer:

            # Un-nest any PGroups

            self.attr['degree'] = self.attr['degree'].flat()
            
        # Get the current event

        self.event = {}
        
        for key in self.attr:

            self.event[key] = self.now(key)

        if self.SynthDef is SamplePlayer:

            # Get the buffer number to play
            self.event['buf'] = BufferManager.symbols.get(self.event['degree'].char, 0)

            # Apply any duration ratio changes
            self.event['dur'] *= self.event['degree'].dur

        return self

    def osc_message(self, index=0):
        """ Creates an OSC packet to play a SynthDef in SuperCollider """

        # Initial message plus custom head and echo variable

        message = ['echoOn', int(self.event['echo'] > 0), 'freq', modi(self.freq, index)]

        for key in self.attr:

            if key not in ('degree', 'oct', 'freq', 'dur', 'offset'):

                try:
                    
                    val = modi(self.event[key], index)

                    if key == "sus":

                        val = val * self.metro.BeatDuration()

                    message += [key, float(val)]

                except:

                    pass

        return message

    def send(self):
        """ Sends the current event data to SuperCollder """

        size = self.tupleN()

        for i in range(size):

            osc_msg = self.osc_message(i)
            
            self.server.sendNote( self.SynthDef, osc_msg )

##            # If echo flag has been set to True - schedule echo decay
##
##            if self.echo_on:
##
##                index = self.event_index
##
##                i = osc_msg.index('amp') + 1
##
##                a = amp = osc_msg[i]
##
##                while amp > 0:
##                    
##                    index += self.echo_fx['delay']
##
##                    amp = amp - (a / self.echo_fx['decay'])
##
##                    i = osc_msg.index('amp') + 1
##
##                    osc_msg[i] = amp
##                    
##                    self.metro.schedule(lambda: self.server.sendNote(self.SynthDef, osc_msg), index )
##
##                print z

        return

    #: Methods for stop/starting players

    def kill(self):
        """ Removes this object from the Clock and resets itself"""
        self.isplaying = False
        self.isAlive = False
        self.event_n = 0
        self.offset = self.attr['offset'] = 0
        return
        
    def stop(self, N=0):
        
        """ Removes the player from the Tempo clock and changes its internal
            playing state to False in N bars time
            - When N is 0 it stops immediately"""

        self.stopping = True        
        self.stop_point = self.metro.now()

        if N > 0:

            self.stop_point += self.metro.NextBar() + ((N-1) * self.metro.Bar())

        return self

    def pause(self):

        self.isplaying = False

        return self

    def play(self):

        self.isplaying = True
        self.stopping = False
        self.isAlive = True

        self.__call__()

        return self

##    def restart(self):
##
##        self.isAlive = True
##        self.stopping = False
##
##        return self

    def follow(self, lead, follow=True):
        """ Takes a now object and then follows the notes """

        if follow:

            self.following = lead

            try:
                self.scale = lead.scale
            except:
                pass

        else:

            self.following = None

        return self

    def solo(self, arg=True):

        if arg:

            self.metro.solo = self

        else:

            self.metro.solo = None

        return self
        

    """
        Feeder Methods
        --------------

        These methods are used in conjunction with Patterns.Feeders functions.
        They change the state of the Player Object and return the object.

        See 'Player.Feeders' for more info on how to use

    """

    def lshift(self, n=1):
        self.event_n -= (n+1)
        return self

    def rshift(self, n=1):
        self.event_n += n
        return self

    def reverse(self):
        """ Sets flag to reverse streams """
        self.reversing = not self.reversing
        return self

    def shuffle(self, attr=None):
        """ Shuffles """
        if attr is None:
            shuffle(self.attr['degree'])
        elif attr in self.attr:
            shuffle(self.attr[attr])
        else:
            print "Player Object has no attribute '{}'".format(attr)

    def multiply(self, n=2):
        self.attr['degree'] = self.attr['degree'] * n
        return self

    def test(self):
        print 'test'
        return self

    """ Every x do y """

    def every(self, n, cmd, args=()):
        try:
            method = getattr(self, cmd)
            assert callable(method)
        except:
            print "Warning: {} is not a valid player method".format(cmd)
            return self
        self.scheduled_events[cmd] = MethodCall(self, cmd, n, args)
        return self
            

##    def _every(self, n, cmd, *args):
##
##        # Creates an expression unique to this object and function
##        e = "'{0}'=='{0}' and '{1}'=='{1}'".format(cmd.__name__, id(self))
##
##        if e not in self.when_statements:
##
##            self.when_statements.append(e)
##
##            self.metro.When(e, lambda: cmd(self), n, nextBar=True)
##
##        else:
##
##            self.metro.when_statements[e].step = n 
##
##        return self

    """

        Modifier Methods
        ----------------

        Other modifiers for affecting the playback of Players

    """

##    def echo(self, stop=False, delay=0.5, decay=10):
##        """ Schedules the current event to repeat and decay """
##        if stop:
##            self.echo_on = False
##        else:
##            self.echo_on = True
##            self.echo_fx['delay'] = delay
##            self.echo_fx['decay'] = decay
##        return self
        

    def offbeat(self, dur=0.5):
        """ Off sets the next event occurence """

        self.offset = self.attr['offset'] = dur

        return self

    def strum(self, dur=0.025):
        """ Adds a delay to a Synth Envelope """
        x = self.tupleN()
        if x > 1:
            self.delay = asStream([tuple(a * dur for a in range(x))])
        else:
            self.delay = asStream(dur)
        return self


    """

        Python's Magic Methods
        ----------------------

        Standard object operation methods

    """

    def __name__(self):
        for name, var in globals().items():
            if self == var: return name

    def __repr__(self):
        return "<Player Instance ('%s')>" % self.SynthDef

    def __str__(self):
        s = "Player Instance using '%s' \n\n" % self.SynthDef
        s += "ATTRIBUTES\n"
        s += "----------\n\n"
        for attr, val in self.attr.items():
            s += "\t{}\t:{}\n".format(attr, val)
        return s


###### GROUP OBJECT

class Group:

    def __init__(self, *args):

        self.players = args

    def __len__(self):
        return len(self.players)

    def __setattr__(self, name, value):
        try:
            for i, p in enumerate(self.players):
                try:
                    setattr(p, name, value)
                except:
                    print "AttributeError: '%s' object has no attribute '%s'" % (str(p), name)
        except:
            self.__dict__[name] = value 
        return self        

    def __getattr__(self, name):
        """ Returns a Pattern object containing the desired attribute for each player in the group  """
        return P([player.__dict__[name] for player in self.players])

    def call(self, method, args):
        for p in self.players:
            p.__dict__[method].__call__(*args)

    def stop(self, n=0):
        for item in self.players:
            item.stop(n)
        return self

    def play(self):
        for item in self.players:
            item.play()
        return self

group = Group
