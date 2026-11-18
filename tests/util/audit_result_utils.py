import collections.abc
import os


def update(orig_dict, new_dict):
    """
    Take new_dict and apply it to orig_dict, When possible, update existing keys, and merge any
    existing lists instead of overwriting them
    :return:
    """
    for key, val in new_dict.items():
        if isinstance(val, collections.abc.Mapping):
            orig_dict[key] = update(orig_dict.get(key, {}), val)
        elif isinstance(val, list):
            orig_dict[key] = orig_dict.get(key, []) + val
        else:
            orig_dict[key] = new_dict[key]
    return orig_dict


def get_filepaths_from_multifileacq_audits(audit_manifest, audit_id=None):
    """
    Given an audit result manifest, this method finds and returns fullpaths of all the files
    that are captured in all the "w32multifileapi-acquisition" and "multifile-acquisition-api" audits
    Note: this can receive a full/part audit "id" value and the results can be filtered on it

    :return: files_in_audit:    list of files in the manifest
        and  found_issues:      whether or not we found issues in the manifest
    """
    audit_generators = ["w32multifileapi-acquisition", "multifile-acquisition-api"]
    files_in_audit = []
    found_issues = False
    fpath_key = "mandiant/mir/agent/FilePath"
    fname_key = "mandiant/mir/agent/FileName"

    for audit in audit_manifest:
        if audit["generator"] in audit_generators and (
            audit_id is None or ("id" in audit and audit["id"].startswith(audit_id))
        ):
            for item in audit["results"]:
                if (
                    item["type"] == "application/vnd.fireeye.xa.issue.v1+json"
                    or item["type"] == "application/vnd.mandiant.issues+xml"
                ):
                    found_issues = True
                elif item["type"] == "application/octet-stream":
                    fpath = next(
                        (
                            metadata["value"]
                            for metadata in item["metadata"]
                            if metadata["name"] == fpath_key
                        ),
                        None,
                    )
                    assert fpath, "Invalid FilePath parameter value in {} audit results".format(
                        audit["generator"]
                    )

                    fname = next(
                        (
                            metadata["value"]
                            for metadata in item["metadata"]
                            if metadata["name"] == fname_key
                        ),
                        None,
                    )
                    assert fname, "Invalid FileName parameter value in {} audit results".format(
                        audit["generator"]
                    )

                    files_in_audit.append(os.path.join(os.path.normpath(fpath), fname))

    return files_in_audit, found_issues