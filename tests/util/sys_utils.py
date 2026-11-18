import logging
import subprocess
from abc import abstractmethod
from subprocess import Popen
from typing import List

import psutil


class SysUtils(object):
    """Utilities for system level functions"""

    logger = logging.getLogger("razor")

    def __init__(self):
        pass

    @classmethod
    def run_command(cls, command, sudo=True, shell=True):
        """Execute a system command and return its stdout.

        Runs through the shell by default so shell builtins (e.g. cmd's ``del``)
        work as expected. Accepts either a command string or a list of args.

        :param command: command to run, as a string or list of arguments
        :param sudo: unused
        :param shell: whether to run the command through the shell
        :return: the command's stdout, or None if the command failed
        """
        try:
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                check=True,
            )
            cls.logger.info("Success: %s", result.stdout)
            return result.stdout
        except subprocess.CalledProcessError as e:
            cls.logger.error("Command failed: %s | stderr: %s", command, e.stderr)
            return None

    @classmethod
    def run_command_background_win(cls, command, sudo=True, shell=True, null_output=True):
        """Run command prompt command in the background

        :param command: command to run in list form
        :param sudo: whether or not to add sudo
        :param shell: whether or not to run in new shell
        """
        cls.logger.debug(" ".join(command))
        if null_output:
            ret_val = subprocess.Popen(
                command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=shell
            )
        else:
            ret_val = subprocess.Popen(command, shell=shell)

        return ret_val
    
    @classmethod
    @abstractmethod
    def run_command_background(
        cls, command: List[str], sudo=True, shell=False, null_output=True
    ) -> Popen:
        pass

    @classmethod
    def ping_win(cls, address):
        """Run ping

        :param address: address to ping
        """
        subprocess.call(["ping", "-n", "5", address])

    @classmethod
    @abstractmethod
    def ping6(cls, address):
        pass

    @classmethod
    @abstractmethod
    def flush_dns(cls):
        pass

    @classmethod
    def flush_dns_win(cls):
        """Flush the DNS cache
        """
        subprocess.call(["ipconfig", "/flushdns"], shell=True)

    @classmethod
    def service_running(cls, service_name):
        """Check if a service is running

        :param service_name: service name to check for
        :return: whether or not the service is running
        """
        return cls.service_in_state(service_name, "running")

    @classmethod
    def service_in_state(cls, service_name, state):
        """Check if a service is in a particular state

        :param service_name: service name to check for
        :param state: state to check for
        :return: whether or not the service is in state
        """
        return state.lower() == cls.get_service_info(service_name).get("status", "")

    @classmethod
    def service_pid(cls, service_name):
        """Get pid of a service

        :param service_name: service to check for
        :return: pid of the service
        """
        return cls.get_service_info(service_name).get("pid", -1)

    @classmethod
    def get_service_info(cls, service_name):
        """Get information about a Windows service.

        :param service_name: name of the service to look up
        :return: dict with the service's ``status`` and ``pid``, or ``{}`` if
            the service does not exist
        """
        service = None
        try:
            service = psutil.win_service_get(service_name)
        except psutil.NoSuchProcess:
            # win_service_get is case-sensitive; fall back to a case-insensitive scan
            for s in psutil.win_service_iter():
                if s.name().lower() == service_name.lower():
                    service = s
                    break
        except Exception as e:  # pragma: no cover - defensive
            cls.logger.debug("Failed to get service info for {}: {}".format(service_name, e))

        if service is None:
            return {}

        info = service.as_dict()
        return {
            "status": info.get("status", ""),
            "pid": info.get("pid") or -1,
        }

    @classmethod
    def start_service(cls, service_name):
        """Start a Windows service.

        :param service_name: name of the service to start
        :return: command output, or None if the command failed
        """
        return cls.run_command("sc start {}".format(service_name))

    @classmethod
    def stop_service(cls, service_name):
        """Stop a Windows service.

        :param service_name: name of the service to stop
        :return: command output, or None if the command failed
        """
        return cls.run_command("sc stop {}".format(service_name))

    @classmethod
    def get_process_info(cls, pid):
        """Acquire generic process info given a PID. If no PID is given, then default to the current
        running python process

        :param pid: process id to get info for
        :return: process information
        """
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                return {
                    "process": process.name(),
                    "processPath": process.exe(),
                    "processPid": process.pid,
                    "parentPid": process.ppid(),
                }
        except psutil.NoSuchProcess:
            cls.logger.debug("Failed to find process with PID: {}".format(pid))
            return {}
