import json
import logging
import os
import re
import shutil
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import psutil
import pytz

from tests.test_eventor_collection.event import Event

logger = logging.getLogger("razor")

def md5_hash_file(filename: Path) -> str:
    """md5 hash a file
    Note: This will pull in the entire file for hashing (i.e. w/o chunking), not recommended for
    very large files.

    :param filename: pathlib Path file to hash
    :return: md5 string
    """
    with filename.open("rb") as file_to_check:
        data = file_to_check.read()
        return hashlib.md5(data).hexdigest()

class ProcessEvent(Event):

    """
    This Event class serves to provide some common members and methods for all
    ProcessEvent triggers (which are subclasses of this class)

    typical Eventor fields collected for this event:
    pid
    parentpid
    startTime
    MD5
    args
    processPath
    process (name)
    parentProcess (name)
    parentProcessPath
    process cmd line
    decoded command line
    """


#############################
#   ProcessEvent triggers   #
#############################


class PythonProcessEvent(ProcessEvent):
    def __init__(
        self, command: str, args: Optional[List[str]] = None,
    ):
        super().__init__()
        self.args = [] if not args else args
        self.command = command
        self.psutil_process = None
        self.sub_proc_process = None
        command_path = shutil.which(command)
        if not command_path:
            logger.debug(f"Environment variables:\n{json.dumps(os.environ.items(), inden=2)}")
            raise FileNotFoundError(
                f"{command} is not recognized as valid command, "
                f"please confirm the program is installed and accessible in "
                f"the PATH/ENV, for reference see the debug log for the "
                f"environment variables"
            )

        # shutil.which capitalizes the ending .exe on Windows
        command_path = Path(re.sub(".EXE$", ".exe", command_path))

        cmd_line = " ".join([self.command] + self.args)

        self.result_info.process = command_path.name
        self.result_info.args = self.args
        self.result_info.processPath = str(command_path)
        self.result_info.processCmdLine = cmd_line
        self.result_info.decodedCmdLine = self.result_info.processCmdLine

    def collect_psutil_info(self):
        # Start event type
        # Switch to oneshot usage to increase success rate
        with self.psutil_process.oneshot():
            try:
                self.result_info.username = self.psutil_process.username()
                # try to collect parent process info, not always successful
                self.result_info.pid = self.psutil_process.pid
                self.result_info.parentProcessPath = self.psutil_process.parent().exe()
                self.result_info.parentProcess = Path(self.result_info.parentProcessPath).name
                self.result_info.parentPid = self.psutil_process.ppid()
            except psutil.NoSuchProcess as error:
                if psutil.pid_exists(self.result_info.pid):
                    logger.error(
                        f"Could not collect stats on process {self.result_info.process},"
                        f" for unknown reasons, dumping available details: "
                        f"{json.dumps(self.result_info, indent=2)}"
                    )
                    raise error
                else:
                    logger.error(
                        f"Could not gather process information, process terminated before "
                        f"stats could be collected, dumping process information collected:"
                        f"{json.dumps(self.result_info, indent=2)}"
                    )
                    raise error

        try:
            self.result_info.md5 = md5_hash_file(Path(self.result_info.processPath))
        except IsADirectoryError:
            raise FileNotFoundError(
                f"File does not exist, path given: {self.result_info.processPath}"
            )

    def trigger_func(self):
        self.result_info.startTime = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self.result_info.timestamp = self.result_info.startTime
        self.result_info.eventType = "start"
        running_process = subprocess.Popen(
            [self.command] + self.args,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            shell=False,
        )
        self.sub_proc_process = running_process
        self.psutil_process = psutil.Process(pid=running_process.pid)
        self.result_info.pid = running_process.pid
        self.collect_psutil_info()

    def post_trigger_func(self):
        """
        This function serves to automatically cleanup the process after details have been
        collected, if the process closed early we will either throw an error here,
        or have already thrown one earlier.
        :return:
        """
        if self.psutil_process.is_running():
            try:
                self.psutil_process.kill()
            except AttributeError:
                raise psutil.NoSuchProcess(
                    f"Process could not be found running and pid was not properly collected, "
                    f"are you sure you ever started the process?"
                )
            return
        else:
            logger.debug("Process was already stopped, this is not an error, continuing..")
            return
