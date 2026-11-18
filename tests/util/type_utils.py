import datetime
import logging
import re

logger = logging.getLogger("tests")

uid_pattern = re.compile(
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
duration_pattern = re.compile(r"PT\d+S")
sid_pattern = re.compile(r"^(?=.{1,184}$)^S-\d-(?:\d+-){1,14}\d+$")
username_pattern = re.compile(r"(?:[\w\-\s])+\\\w+")
md5_pattern = re.compile(r"([a-fA-F\d]{32})")
sha1_pattern = re.compile(r"([a-fA-F\d]{40})")
sha256_pattern = re.compile(r"([a-fA-F\d]{64})")
pe_hash_pattern = re.compile(r"([0-9a-fA-F\s]{2,})")
filepath_pattern = re.compile(r"([\w:\\]+[\\\w+]+.\w+)")


def is_collection_string_type(collection):
    return is_collection_of_n_type(collection, is_string_type)


def is_collection_of_n_type(collection, type_expected):
    # only supports a collection with all the same types right now
    return all([type_expected(item) for item in collection])


def is_numeric_type(number):
    return isinstance(number, int)


def is_pid_type(pid):
    return isinstance(pid, int)


def is_string_type(string):
    return isinstance(string, str)


def is_duration_type(duration):
    valid_str = is_string_type(duration)
    return valid_str and duration_pattern.fullmatch(duration)


def is_filepath_type(path):
    if not is_string_type(path):
        return False
    # Extended-length (\\?\C:\...) and NT (\??\C:\...) prefixes are valid Windows paths.
    for prefix in ("\\\\?\\", "\\??\\"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return filepath_pattern.match(path)


def is_sid_type(sid):
    valid_str = is_string_type(sid)
    return valid_str and sid_pattern.match(sid)


def is_username_type(username):
    valid_str = is_string_type(username)
    return valid_str and username_pattern.match(username) is not None


def is_iso_8601_time_type(timestamp):
    valid_str = is_string_type(timestamp)
    # Parse the time into a datetime object
    try:
        datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return valid_str


def is_uid_type(uid):
    valid_str = is_string_type(uid)
    return valid_str and uid_pattern.fullmatch(uid) is not None


def is_bool_type(boolean):
    # Currently in memory audits the item is a string of either 'false' or 'true'
    bool_str_list = ["false", "true"]
    return is_string_type(boolean) and boolean in bool_str_list


def is_md5_type(hash_string):
    # fullmatch: a longer hex string (e.g. a SHA1 in an MD5 field) must not pass
    return is_string_type(hash_string) and md5_pattern.fullmatch(hash_string)


def is_sha1_type(hash_string):
    return is_string_type(hash_string) and sha1_pattern.fullmatch(hash_string)


def is_sha256_type(hash_string):
    return is_string_type(hash_string) and sha256_pattern.fullmatch(hash_string)


def is_pe_hash_type(pe_hash):
    return is_string_type(pe_hash) and pe_hash_pattern.match(pe_hash)