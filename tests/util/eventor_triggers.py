import logging
import time
from datetime import datetime

import pytz
from tests.util.constants import RAZOR_PUBLIC
from tests.test_eventor_collection.file_events import FileEvent
from tests.util.sys_utils import SysUtils
from tests.util.util import random_string

logger = logging.getLogger("eventor_triggers")


class DirEvent(FileEvent):
    def __init__(self, target_dir=None, dest_dir=None):
        super().__init__()
        self.target_dir = target_dir
        self.dest_dir = dest_dir

    def collect_info(self, member):
        # collect dir relevant info *No super call here b/c of hashing attempt*
        self.result_info["fullPath"] = str(member)
        self.result_info["closed"] = 1
        self.result_info["filePath"] = self.gen_filepath(member)
        self.result_info["fileName"] = member.name
        self.result_info["fileExtension"] = ""
        self.result_info["file_obj"] = member
        self.result_info["size"] = 0
        self.result_info["writes"] = 0

    def pre_trigger_func(self):
        """
        Create the initial dir if the target dir doesn't exist
        :return:
        """
        if not self.target_dir.is_dir():
            self.target_dir.mkdir()
            time.sleep(1)


class DirRenameEvent(DirEvent):
    def __init__(self, target_dir=None, dest_dir=None):
        target_dir = target_dir if target_dir else RAZOR_PUBLIC / random_string(8)
        dest_dir = (
            dest_dir if dest_dir else RAZOR_PUBLIC / "{}{}".format(random_string(), "_renamed_dir")
        )
        super().__init__(target_dir=target_dir, dest_dir=dest_dir)

    def trigger_func(self):
        """
        Rename an already created directory or create a new dir and then rename it
        :return:
        """

        # Main custom trigger
        # reassign the target file to it's updated location.
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self.target_dir.rename(self.dest_dir)
        # collect after the trigger here b/c of target_file reassignment
        self.collect_info(self.dest_dir)


class DirDeleteEvent(DirEvent):
    def __init__(self, target_dir=None):
        target_dir = target_dir if target_dir else RAZOR_PUBLIC / random_string(8)
        super().__init__(target_dir=target_dir)

    def trigger_func(self):
        """
        Delete an already created directory or create a new dir and then delete it
        :return:
        """

        # Main custom trigger
        # collect before the trigger here b/c of target_dir deletion
        self.collect_info(self.target_dir)
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        # For some unknown reason, probably handles not being cleared on the OS,
        # we need to use the sysutils commands here to cleanly remove the dir
        command = "rd /s /q {}".format(str(self.target_dir))
        SysUtils.run_command(command)
