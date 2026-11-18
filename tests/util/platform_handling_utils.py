import logging

logger = logging.getLogger("util")


def full_path_to_lowercase(data, iterate=True):
    if iterate:
        for event in data["eventItem"]:
            if "fileWriteEvent" not in event:
                continue
            if "fullPath" not in event["fileWriteEvent"]:
                continue
            event["fileWriteEvent"]["fullPath"] = event["fileWriteEvent"]["fullPath"].lower()
        return data["eventItem"]

    if "fullPath" in data:
        data["fullPath"] = data["fullPath"].lower()
    return data["fullPath"]


def image_load_process_to_lowercase(data, iterate=True):
    """Lowercase ``process`` of imageLoadEvent items (iterate=True) or of a filter dict.
    Only imageLoadEvent items are touched; other event types keep their values."""
    if iterate:
        for event in data["eventItem"]:
            if "imageLoadEvent" not in event:
                continue
            if "process" not in event["imageLoadEvent"]:
                continue
            event["imageLoadEvent"]["process"] = event["imageLoadEvent"]["process"].lower()
        return data["eventItem"]

    if "process" in data:
        data["process"] = data["process"].lower()
    return data["process"]


def path_to_uppercase(data, iterate=True):
    if iterate:
        for event in data["eventItem"]:
            if "regKeyEvent" not in event:
                continue
            if "path" not in event["regKeyEvent"]:
                continue
            event["regKeyEvent"]["path"] = event["regKeyEvent"]["path"].upper()
        return data["eventItem"]

    if "path" in data:
        data["path"] = data["path"].upper()
    return data["path"]


def key_path_to_uppercase(data, iterate=True):
    if iterate:
        for event in data["eventItem"]:
            if "regKeyEvent" not in event:
                continue
            if "keyPath" not in event["regKeyEvent"]:
                continue
            event["regKeyEvent"]["keyPath"] = event["regKeyEvent"]["keyPath"].upper()
        return data["eventItem"]

    if "keyPath" in data:
        data["keyPath"] = data["keyPath"].upper()
    return data["keyPath"]


def hive_to_uppercase(data, iterate=True):
    if iterate:
        for event in data["eventItem"]:
            if "regKeyEvent" not in event:
                continue
            if "hive" not in event["regKeyEvent"]:
                continue
            event["regKeyEvent"]["hive"] = event["regKeyEvent"]["hive"].upper()
        return data["eventItem"]

    if "hive" in data:
        data["hive"] = data["hive"].upper()
    return data["hive"]