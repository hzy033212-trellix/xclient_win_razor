import logging
import os
import shutil
import time
from datetime import datetime
import pytz
from tests.test_eventor_collection.event import Event
from tests.util.sys_utils import SysUtils
from tests.util.util import func_wait


class ImageLoadEvent(Event):

    """
    This Event class serves to provide some common members and methods for all
    ImageLoadEvent triggers (which are subclasses of this class)
    """

    def __init__(self, library: str):
        super().__init__()
        self.library = str(library)
        self.result_info = {}


#############################
#  ImageLoadEvent triggers  #
#############################


class ImageLoadServiceStartEvent(ImageLoadEvent):
    """ImageLoadServiceStartEvent trigger"""

    def __init__(self, service_name: str, library: str):
        self.service_name = str(service_name)
        super().__init__(library=library)

    def trigger_func(self):
        """
        Start a service with known dependent shared libaries
        :return:
        """
        if SysUtils.service_running(self.service_name):
            SysUtils.stop_service(self.service_name)

            def for_service_stop():
                return not SysUtils.service_running(self.service_name)

            service_stopped = func_wait(for_service_stop, interval=3, timeout=30)
            if not service_stopped:
                raise Exception("Failed to stop running service: {}".format(self.service_name))

        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)

        SysUtils.start_service(self.service_name)

        def for_service_start():
            if SysUtils.service_running(self.service_name):
                return SysUtils.service_pid(self.service_name)
            return False

        service_pid = func_wait(for_service_start, interval=3, timeout=15)
        if not service_pid:
            raise Exception("Failed to start service: {}".format(self.service_name))

        service_info = SysUtils.get_process_info(service_pid)
        if service_info == {}:
            raise Exception(
                "Failed to collect service info for {} with PID: {}".format(
                    self.service_name, service_pid
                )
            )

        self.result_info["fileName"] = self.library
        self.result_info["pid"] = service_pid
        self.result_info["process"] = service_info["process"]
        self.result_info["processPath"] = service_info["processPath"]


class ImageLoadExecutableStartEvent(ImageLoadEvent):
    """ImageLoadExecutableStartEvent trigger"""

    def __init__(self, executable: str, library: str):
        self.executable_path = shutil.which(executable)
        if not self.executable_path:
            raise FileNotFoundError("{} is not recognized as valid executable".format(executable))
        self.executable_name = os.path.basename(self.executable_path)
        super().__init__(library=library)

    def trigger_func(self):
        """
        Start an executable with known dependencies libaries
        :return:
        """
        SysUtils.run_command_background_win([self.executable_path])
        
#       logging.info("Sleep for 60 seconds to make sure ALL dlls have been loaded!")
#       time.sleep(60)  # Make sure ALL dlls have been loaded!

        self.result_info["fileName"] = self.library
        self.result_info["process"] = self.executable_name
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
