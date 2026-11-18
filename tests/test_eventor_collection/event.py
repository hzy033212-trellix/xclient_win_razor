import datetime
import math
import time
from abc import abstractmethod

import psutil
import pytz
from addict import Dict


class Event:

    """
    This class serves as the base class for all event.py types and is expected to be subclassed.
    Specific event.py types will provide their own implementations for the listed methods in this
    class.
    """

    _process = psutil.Process()
    with _process.oneshot():
        _process_name = _process.name()
        _process_path = _process.exe()
        _process_pid = _process.pid
        _process_ppid = _process.ppid()

    def __init__(self):
        """
        During event trigger creation there are some fields which are common enough that they are
        instantiated here in the Event base class constructor. Everything below CAN be overridden
        but it is up to the subclass implementors to make sure they retrieve the proper
        information.
        """
        self.pre_trigger_duration, self.trigger_duration, self.post_trigger_duration = 0, 0, 0
        self.total_duration = 0
        self.result_info = Dict(
            {
                "process": self._process_name,
                "processPath": self._process_path,
                "pid": self._process_pid,
                "parentPid": self._process_ppid,
            }
        )
        self.pre_trigger_timestamp = None
        self.trigger_timestamp = None
        self.str_trigger_timestamp = None
        self.post_trigger_timestamp = None

    def __str__(self):
        return type(self).__name__

    def trigger(self) -> Dict:
        """
        **Please see trigger_func() entries for specific trigger details**

        This function wraps up pre/post and trigger subclass methods and executes them in a
        commonly defined way. This is the method intended to be used when generating recognizable
        events.

        :return: result_info dict containing event information for validating against
        """

        # Events from eventor only have 3 digits in microsecond
        def get_rounded_timestamp():
            ts = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            ts = ts.replace(microsecond=math.floor(ts.microsecond / 1000) * 1000)
            return ts, ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        tic = time.time()
        self.pre_trigger_timestamp, _ = get_rounded_timestamp()
        self.pre_trigger_func()
        self.pre_trigger_duration = time.time() - tic

        try:
            tic = time.time()
            self.trigger_timestamp, self.str_trigger_timestamp = get_rounded_timestamp()
            self.trigger_func()
            self.trigger_duration = time.time() - tic
        finally:
            tic = time.time()
            self.post_trigger_timestamp, _ = get_rounded_timestamp()
            self.post_trigger_func()
            self.post_trigger_duration = time.time() - tic

        self.total_duration = (
            self.pre_trigger_duration + self.trigger_duration + self.post_trigger_duration
        )

        return self.result_info

    @abstractmethod
    def trigger_func(self):
        """"""
        pass

    def pre_trigger_func(self):
        """"""
        pass

    def post_trigger_func(self):
        """"""
        pass