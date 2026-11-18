import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
import pytz

from tests.util.paths import RAZOR_PUBLIC
from tests.test_eventor_collection.event import Event
from tests.util.sys_utils import SysUtils
from tests.util.util import (
    random_string,
    md5_hash_file,
    random_unicode_mixed,
)

DELETE_SLEEP = 1

class FileEvent(Event):
    """
    This Event class serves to provide some common members and methods for all FileEvent
    triggers (which are subclasses of this class)
    """

    def __init__(self, target_file=None, dest_dir=None, encoding="utf-8"):
        super().__init__()
        self.encoding = encoding
        if target_file:
            self.target_file = target_file
        else:
            self.target_file = RAZOR_PUBLIC / "{}.txt".format(random_string())
        self.dest_dir = dest_dir if dest_dir else RAZOR_PUBLIC / random_string()

        self.result_info["drive"] = self.target_file.drive[0:-1]
        # Not implemented
        # self.result_info["lowestFileOffsetSeen"]
        # self.result_info["dataAtLowestOffset"]
        # self.result_info["openDuration"]

        # This will remain constant until there is a reasonable method for triggering the 6
        # hour timeout that currently exists
        self.result_info["eventReason"] = "File closed"
        # Set to 1 by default, can be updated within individual triggers if needed.
        self.result_info["writes"] = 1

        self.result_info["fullPath"] = str(self.target_file)
        self.result_info["closed"] = 1
        self.result_info["numBytesSeenWritten"] = 0
        self.result_info["filePath"] = self.gen_filepath(self.target_file)
        self.result_info["fileName"] = self.target_file.name
        self.result_info["file_obj"] = self.target_file

        # Not implemented
        # self.result_info["devicePath"]
        # Missing ENV vars will cause this to error out. choosing to not implement for now.
        # self.result_info["username"] = getpass.getuser()

    @staticmethod
    def gen_filepath(member):
        """

        :param member:
        :type member:
        :return:
        :rtype:
        """
        return str(Path(*member.parent.parts[1:]))

    def collect_info(self, member):
        """
        Collects information about the file included in the results.
        :param member: a Path object which should exist on disk
        :return: N/A
        """
        self.result_info["fullPath"] = str(member.resolve())
        # Remove leading '.' for agent compatibility
        if member.suffix:
            self.result_info["fileExtension"] = "".join(member.suffixes)[1:]
        else:
            self.result_info["fileExtension"] = ""
        self.result_info["closed"] = 1
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self.result_info["md5"] = md5_hash_file(member)
        self.result_info["size"] = member.stat().st_size
        self.result_info["filePath"] = self.gen_filepath(member)
        self.result_info["fileName"] = member.name
        self.result_info["file_obj"] = member


#############################
#    FileEvent triggers     #
#############################


class FileRenameEvent(FileEvent):
    """"""

    def __init__(self, target_file=None, dest_dir=None):
        """

        :type target_file: Path
        """
        super().__init__(target_file=target_file, dest_dir=dest_dir)

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        self.result_info["writes"] = 0
        self.result_info["numBytesSeenWritten"] = 0

    def trigger_func(self):
        """
        Rename the target file thus moving it one directory to another. Within the same physical
        disk A move operation is actually just a rename operation. Across disks it is typically a
        copy and delete operation.
        :return:
        """

        # Main custom trigger
        if not self.target_file.exists():
            self.target_file.touch()
        self.dest_dir.mkdir()
        # reassign the target file to it's updated location.
        self.target_file = Path(shutil.move(str(self.target_file), str(self.dest_dir)))
        # collect after the trigger here b/c of target_file reassignment
        self.collect_info(self.target_file)


class FileCreateEvent(FileEvent):
    """"""

    def __init__(self, target_file=None):
        self.file_text = "some text"
        super().__init__(target_file=target_file)

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        self.result_info["textAtLowestOffset"] = self.file_text
        self.result_info["numBytesSeenWritten"] = len(self.file_text.encode(self.encoding))
        self.result_info["file_contents"] = self.file_text

    def pre_trigger_func(self):
        """"""
        if self.target_file.is_file():
            self.target_file.unlink()

    def trigger_func(self):
        """
        Create a new file on the disk.
        :return:
        """
        # Main custom trigger
        self.target_file.write_text(self.file_text, encoding=self.encoding)
        self.collect_info(self.target_file)


class FileWriteEvent(FileEvent):
    """"""

    def __init__(
        self, file_contents=None, target_file=None, dest_dir=None, encoding="utf-8",
    ):
        super().__init__(target_file=target_file, dest_dir=dest_dir, encoding=encoding)
        self.file_contents = (
            file_contents if file_contents else bytes(random_string(500), encoding=self.encoding)
        )
        if isinstance(self.file_contents, (bytes, bytearray)):
            self.file_contents_length = len(self.file_contents)
        else:
            self.file_contents_length = len(
                self.file_contents.encode(self.encoding, "surrogatepass")
            )

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        self.result_info["numBytesSeenWritten"] = self.file_contents_length

    def _write_contents(self):
        if isinstance(self.file_contents, (bytes, bytearray)):
            self.target_file.write_bytes(self.file_contents)
            self.result_info["textAtLowestOffset"] = self.file_contents[0:64].decode(self.encoding)
        if isinstance(self.file_contents, str):
            self.target_file.write_text(self.file_contents, encoding=self.encoding)
            self.result_info["textAtLowestOffset"] = self.file_contents[0:64]

    def pre_trigger_func(self):
        """
        Create the parent dir if it does not exist
        :return:
        """
        if not self.target_file.parent.exists():
            self.target_file.parent.mkdir(parents=True)

        super().pre_trigger_func()

    def trigger_func(self):
        """
        Rename either an existing file (by specifying the target_file when creating the class,
        or create a new file (the standard associated file with this class (target_file) and then
        rename it immediately.
        :return: a result object
        """
        # Main custom trigger
        self._write_contents()
        self.collect_info(self.target_file)


class FileDeleteEvent(FileEvent):
    """"""

    def __init__(self, target_file=None):
        if target_file:
            super().__init__(target_file=target_file)
        else:
            file_to_delete = RAZOR_PUBLIC / "{}{}{}".format(random_string(10), "_delete", ".txt")
            super().__init__(target_file=file_to_delete)

    def pre_trigger_func(self):
        """
        :return:
        """
        file_text = "prepopulated text"
        if not self.target_file.exists():
            self.target_file.write_text(file_text, encoding=self.encoding)
        self.result_info["createTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        # Hold for a moment This helps ensure the first event related to creation is captured and
        # does not interfere with the subsequent delete event
        time.sleep(DELETE_SLEEP)

    def trigger_func(self):
        """
        Rename either an existing file (by specifying the target_file when creating the class,
        or create a new file (the standard associated file with this class (target_file) and then
        rename it immediately.
        :return: a result object
        """
        # Main custom trigger
        # delete it, but before that collect info about the file.
        self.collect_info(self.target_file)
        # For some unknown reason, probably handles not being cleared on the OS,
        # we need to use the sysutils commands here to cleanly remove the file
        SysUtils.run_command(f"del {self.target_file}")


###################################
#    FileCreateEvent triggers     #
###################################


class FileCreateAsciiEvent(FileCreateEvent):
    pass


class FileCreateUnicodeEvent(FileCreateEvent):
    """"""

    def __init__(self, unicode_name=None, target_file=None):
        unicode_name = unicode_name if unicode_name else random_unicode_mixed()
        target_file = target_file if target_file else RAZOR_PUBLIC / "{}.txt".format(unicode_name)
        super().__init__(target_file=target_file)


class FileCreateLinkEvent(FileCreateEvent):
    """
    Based class which will cover the link events. Should have common setup for each of these
    sub-triggers
    """

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        # Overwrite super
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)

    def pre_trigger_func(self):
        """
        :return: N/A
        """
        if not self.target_file.exists():
            self.target_file.write_text(
                "A new file which will be linked to.", encoding=self.encoding
            )


class FileCreateSoftLinkEvent(FileCreateLinkEvent):
    """
    File create soft/symlink event trigger. This is the only
    """

    def __init__(self, softlink_file=None, target_file=None):
        super().__init__(target_file=target_file)
        if softlink_file:
            self.symlink = softlink_file
        else:
            link_name = "{}{}{}".format(self.target_file.stem, "_symlink", self.target_file.suffix)
            self.symlink = Path(self.target_file.parent) / link_name

    def trigger_func(self):
        """
        Create a new soft link to the target_file. Users of this trigger cannot specify link file
        info, so we create it here and make the link. Returned information will reference the
        link created and NOT the link target.
        :return:
        """
        # Main custom trigger
        # make a symlink file to another file
        self.symlink.symlink_to(self.target_file, target_is_directory=False)
        self.collect_info(self.symlink)
        # Override the resolve request in parent classes due to symlink being the target
        self.result_info["fullPath"] = str(self.symlink)


class FileCreateHardLinkEvent(FileCreateLinkEvent):
    """
    File create hard link event trigger.
    """

    def __init__(self, hardlink_file=None, target_file=None):
        super().__init__(target_file=target_file)
        if hardlink_file:
            if hardlink_file.exists():
                raise FileExistsError(
                    "hardlink_file must not exist, found: {}".format(str(hardlink_file))
                )
            self.hardlink = hardlink_file
        else:
            link_name = "{}{}{}".format(self.target_file.stem, "_hardlink", self.target_file.suffix)
            self.hardlink = Path(self.target_file.parent) / link_name

    def trigger_func(self):
        """
        Create a new hard link to the target_file. Users of this trigger cannot specify link file
        info, so we create it here and make the link. Returned information will reference the
        link created and NOT the link target.
        :return:
        """
        # Main custom trigger
        # make a hardlink file to another file
        os.link(self.target_file, self.hardlink)
        self.collect_info(self.hardlink)


###################################
#    FileDeleteEvent triggers     #
###################################


class FileDeleteLinkEvent(FileDeleteEvent):
    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        # Remove leading '.' for agent compatibility
        self.result_info["closed"] = 1
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)

    def pre_trigger_func(self):
        """
        :return:
        """
        file_text = "prepopulated text"
        if not self.target_file.exists():
            self.target_file.write_text(file_text, encoding=self.encoding)
        self.result_info["createTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        # Hold for a moment This helps ensure the first event related to creation is captured and
        # does not interfere with the subsequent delete event
        time.sleep(DELETE_SLEEP)


class FileDeleteSoftLinkEvent(FileDeleteLinkEvent):
    """
    File delete soft/symlink event trigger.
    """

    def __init__(self, link_to_delete=None, target_file=None):
        if not link_to_delete:
            link_to_delete = RAZOR_PUBLIC / "{}{}{}".format(
                random_string(10), "_delete_sym", ".txt"
            )
        self.symlink = link_to_delete
        super().__init__(target_file=target_file)

    def pre_trigger_func(self):
        """
        :return:
        """
        # This super call will initialise the target_file if needed
        super().pre_trigger_func()
        if not self.symlink.exists():
            self.symlink.symlink_to(self.target_file, target_is_directory=False)
        self.result_info["createTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        # Hold for a moment This helps ensure the first event related to creation is captured and
        # does not interfere with the subsequent delete event
        time.sleep(DELETE_SLEEP)

    def trigger_func(self):
        """"""
        # Main custom trigger
        self.collect_info(self.symlink)
        # For some unknown reason, probably handles not being cleared on the OS,
        # we need to use the sysutils commands here to cleanly remove the file
        command = "del {}".format(str(self.symlink))
        SysUtils.run_command(command)


class FileDeleteHardLinkEvent(FileDeleteLinkEvent):
    """
    File delete hard link event trigger.
    """

    def __init__(self, link_to_delete=None, target_file=None):
        if not link_to_delete:
            link_to_delete = RAZOR_PUBLIC / "{}{}{}".format(
                random_string(10), "_delete_hard", ".txt"
            )
        self.hardlink = link_to_delete
        super().__init__(target_file=target_file)

    def pre_trigger_func(self):
        """
        This helper function will allow users to pre-populate the file on disk which will be
        deleted in the trigger function.
        :return:
        """
        super().pre_trigger_func()
        if not self.hardlink.exists():
            os.link(self.target_file, self.hardlink)
            self.result_info["md5"] = md5_hash_file(self.hardlink)
        self.result_info["createTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        # Hold for a moment This helps ensure the first event related to creation is captured and
        # does not interfere with the subsequent delete event
        time.sleep(DELETE_SLEEP)

    def trigger_func(self):
        """"""
        # Main custom trigger
        self.collect_info(self.hardlink)
        # For some unknown reason, probably handles not being cleared on the OS,
        # we need to use the sysutils commands here to cleanly remove the file
        command = "del {}".format(str(self.hardlink))
        SysUtils.run_command(command)


##################################
#    FileWriteEvent triggers     #
##################################


class FileWriteAsciiEvent(FileWriteEvent):
    pass


class FileWriteUnicodeEvent(FileWriteEvent):
    def __init__(
        self,
        encoding="utf-8",
        unicode_name=None,
        file_contents=None,
        target_file=None,
        dest_dir=None,
    ):
        unicode_name = unicode_name if unicode_name else random_unicode_mixed()
        file_contents = file_contents if file_contents else random_unicode_mixed()
        target_file = target_file if target_file else RAZOR_PUBLIC / "{}.txt".format(unicode_name)
        super().__init__(
            file_contents=file_contents,
            target_file=target_file,
            dest_dir=dest_dir,
            encoding=encoding,
        )


class FileCopyEvent(FileWriteEvent):
    """
    Take in desired copy file name, target_file refers to the original file which will be copied
    in this trigger.
    """

    def __init__(self, copied_file=None, target_file=None, dest_dir=None):
        super().__init__(target_file=target_file, dest_dir=dest_dir)
        if copied_file:
            if copied_file.exists():
                raise FileExistsError(
                    "copied_file path obj must not exist, found: {}".format(str(copied_file))
                )
            self.copied_file = copied_file
        else:
            new_name = f"{self.target_file.stem}_copy{self.target_file.suffix}"
            self.copied_file = Path(self.dest_dir) / new_name

    def pre_trigger_func(self):
        """"""
        if not self.dest_dir.exists():
            self.dest_dir.mkdir(parents=True)
        # write the target_file if it doesn't already exist
        if not self.target_file.exists():
            self._write_contents()

    def trigger_func(self):
        """
        Copy the pretrigger created file to another location
        :return: a result object
        """
        # Main custom trigger
        # Copy the file using the initially created file from pretrigger
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        shutil.copy2(str(self.target_file), str(self.copied_file))
        # At this point new_file_copy should reference the new copy
        if not self.copied_file.exists():
            raise FileNotFoundError("The file copy operation was not successful.")
        super().collect_info(self.copied_file)
        self.result_info["numBytesSeenWritten"] = self.file_contents_length
        self.result_info["md5"] = md5_hash_file(self.copied_file)
        self.result_info["size"] = self.target_file.stat().st_size
        self.result_info["file_obj"] = self.target_file


class FileWriteRedirectEvent(FileWriteEvent):
    """
    This class explicitly deals with the creation of a file via a redirected stream.
    """

    def trigger_func(self):
        """"""
        # TODO: implement
        pass


class FileWriteRedirectExternalProcEvent(FileWriteEvent):
    """
    This requires forcing an existing system exe to dump to disk. The information that needs to
    be covered should be indicated in the description of this class.
    """

    def trigger_func(self):
        """"""
        # TODO: implement
        pass


class FileWriteAppendEvent(FileWriteEvent):
    """
    Either take in an existing file which we will append to, or create a file in pre-trigger and
    then append data to the file in the trigger function
    """

    def __init__(self, append_data=None, target_file=None, encoding="utf-8"):
        super().__init__(target_file=target_file, encoding=encoding)
        self.append_data = (
            append_data if append_data else bytes(random_string(40), encoding=self.encoding)
        )
        self.byte_mode = False
        if isinstance(self.append_data, (bytes, bytearray)):
            self.append_data_length = len(self.append_data)
            self.byte_mode = True
        else:
            self.append_data_length = len(self.append_data.encode(self.encoding, "surrogatepass"))

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        self.result_info["numBytesSeenWritten"] = self.append_data_length

    def pre_trigger_func(self):
        """"""
        if not self.target_file.exists():
            self._write_contents()

    def trigger_func(self):
        """
        Append text to the target file
        :return:
        """
        # Main custom trigger
        if self.byte_mode:
            with open(self.target_file, "ab") as appendee:
                appendee.write(self.append_data)
            self.result_info["textAtLowestOffset"] = self.append_data[0:64].decode(self.encoding)
        else:
            with open(self.target_file, "a", encoding="utf-8") as appendee:
                appendee.write(self.append_data)
            self.result_info["textAtLowestOffset"] = self.append_data[0:64]

        self.collect_info(self.target_file)


class FileTruncateEvent(FileWriteEvent):
    """
    File truncate event trigger.
    """

    def __init__(self, initial_data=None, file_offset=None, target_file=None):
        self.initial_data = initial_data if initial_data else "remaining text | removed text"
        self.file_offset = file_offset if file_offset else 14
        super().__init__(file_contents=self.initial_data, target_file=target_file)

    def collect_info(self, member):
        """

        :param member:
        :type member:
        """
        super().collect_info(member)
        # Need to overwrite most of what is assigned in super.
        self.result_info["textAtLowestOffset"] = self.file_contents[: self.file_offset]
        self.result_info["initialData"] = self.initial_data
        self.result_info["size"] = self.target_file.stat().st_size
        self.result_info["md5"] = md5_hash_file(self.target_file)
        self.result_info["file_obj"] = self.target_file
        self.result_info["numBytesSeenWritten"] = self.file_offset

    def pre_trigger_func(self):
        """
        This helper function will allow users to pre-populate the file on disk which will be
        deleted in the trigger function.
        :return:
        """
        self.result_info["createTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self._write_contents()

    # def trigger_func(self):
    #     """"""
    #     with open(self.target_file, "r+") as fo:
    #         fo.seek(0)
    #         # remove all the text after offset
    #         fo.truncate(self.file_offset)

    #     # Result info relevant to the trigger
    #     self.collect_info(self.target_file)

    def trigger_func(self):
        """
        Trigger the file truncate event.
        :return:
        """
        # Path to your file
        file_path = self.target_file
        # Number of characters to keep
        keep_length = self.file_offset
        logging.info(f"Truncating file '{file_path}' to keep length {keep_length}")
        if os.path.exists(file_path):
            # 1. Read the existing contents
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 2. Truncate the text shorter
            truncated_content = content[:keep_length]
            # 3. Save the modified content back to the file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(truncated_content)
            logging.info(f"File '{file_path}' truncated successfully.")
        else:
            logging.info(f"File '{file_path}' not found.")
        self.collect_info(self.target_file)


#############################
# Lightweight file triggers #
#############################


class FastFileEvent:
    """ Creates a file on disk while removing most of the overhead associated with the event field
    validation triggers. This trigger is primarily concerned with running the highest number of
    triggers possible. When trying to rate limit for soak testing, it is recommended to use
    triggers with more fields/information in the results.
    """

    def __init__(self, target_file=None):
        self.file_text = b"some text"
        if target_file:
            self.target_file = target_file
        else:
            self.target_file = RAZOR_PUBLIC / "{}.txt".format(random_string())
        self.result_info = {}

    def trigger(self):
        """
        Create a new file on the disk.
        :return: result_info dictionary
        """
        # Main custom trigger
        tic = time.time()
        self.result_info = {}
        self.target_file.write_bytes(self.file_text)
        self.result_info["file_obj"] = self.target_file
        self.result_info["fileName"] = self.target_file.name
        self.result_info["fullPath"] = str(self.target_file)
        self.result_info["openTime"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self.total_duration = time.time() - tic
        return self.result_info


class FastFileAppendEvent:
    """This class is used to exclusively show that created and instantiated triggers will be
    repeatedly called. With properly designed trigger methods this has the effect of running the
    same `n` actions each time the stresser returns.
    """

    def __init__(self):
        self.file_text = None
        self.target_file = RAZOR_PUBLIC / "{}.txt".format(random_string())
        self.result_info = {}

    def trigger(self):
        tic = time.time()
        # Main custom trigger
        self.result_info = {}
        self.file_text = random_string(20)
        with open(self.target_file, "a") as f:
            f.write(self.file_text)
        self.result_info["timestamp"] = datetime.utcnow().replace(tzinfo=pytz.UTC)
        self.total_duration = time.time() - tic
        return self.result_info