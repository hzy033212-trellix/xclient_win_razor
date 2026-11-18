import logging
import re

import pefile

from tests.util.schema_utils import return_section_schema_checks
from tests.util.string_formatting_utils import pprint_base_formatter, pprint_missing_fields_failure
from tests.util.type_utils import is_numeric_type, is_string_type

logger = logging.getLogger("tests")


#################################################
# Utilities for grabbing information from files #
#################################################


def collect_imports_from_pefile(filepath):
    """
    Take in the filepath
    :param filepath: pathlib filepath
    :return: list of import names and information
    """
    test_binary = pefile.PE(filepath)

    try:
        imports_and_functions = []
        for entry in test_binary.DIRECTORY_ENTRY_IMPORT:
            # Imports by ordinal are left out even when pefile gives them a name: for
            # well-known DLLs (OLEAUT32, WS2_32) pefile looks the ordinal up in a
            # built-in table, and the result differs between pefile versions
            # ("ord450" in 2018.5.24, "HWND_UserMarshal64" in 2024.8.26). XClient
            # doesn't report a function name for them either; see
            # is_xclient_ordinal_placeholder().
            imported_functions = [
                imp.name.decode("utf-8")
                for imp in entry.imports
                if hasattr(imp, "name") and hasattr(imp.name, "decode")
                and not getattr(imp, "import_by_ordinal", False)
            ]
            import_item = {
                "Name": entry.dll.decode("utf-8"),
                "ImportedFunctions": imported_functions,
            }
            imports_and_functions.append(import_item)
    except AttributeError:
        raise AttributeError("Unable to collect IMPORTS from PEFile: {}".format(filepath.name))
    finally:
        test_binary.close()

    return imports_and_functions


_ORDINAL_EXPORT = re.compile(r"^Ordinal:\d+$")
_ORDINAL_DRIVER_IMPORT = re.compile(r"^[^:\\/]+\.(dll|exe|sys):\d+$", re.IGNORECASE)


def is_xclient_ordinal_placeholder(function_name, module_name=None):
    """True for the names XClient puts in place of an import or export that has
    no name (it's imported or exported by ordinal only):

      exports                                ``Ordinal:0008``
      driver imports (drivers-signature)     ``<dll>:<ordinal>``, e.g. ``ntoskrnl.exe:0004``
      process imports (processes-memory)     the imported module's own name, e.g.
                                             ``USER32.dll`` under module ``USER32.dll``

    pefile doesn't report these by name (collect_imports_from_pefile and
    collect_exports_from_pefile leave them out), so the PE comparison tests drop
    them from the audit side too.
    """
    if not function_name:
        return False
    if _ORDINAL_EXPORT.match(function_name) or _ORDINAL_DRIVER_IMPORT.match(function_name):
        return True
    return bool(module_name) and function_name.lower() == module_name.lower()


def collect_named_export_ordinals(filepath):
    """{ordinal: name} for the exports of ``filepath`` that have a name ({} if it
    has no export table). Used to spot XClient reporting a named export by
    ordinal only (``Ordinal:<n>``)."""
    test_binary = pefile.PE(filepath)
    try:
        directory = getattr(test_binary, "DIRECTORY_ENTRY_EXPORT", None)
        if directory is None:
            return {}
        return {
            exp.ordinal: exp.name.decode("utf-8")
            for exp in directory.symbols
            if hasattr(exp, "name") and hasattr(exp.name, "decode")
        }
    finally:
        test_binary.close()


def xclient_ordinal_export_number(function_name):
    """The ordinal in XClient's ``Ordinal:<n>`` export placeholder, else None."""
    if function_name and _ORDINAL_EXPORT.match(function_name):
        return int(function_name.split(":", 1)[1])
    return None


def collect_exports_from_pefile(filepath):
    test_binary = pefile.PE(filepath)
    try:
        exported_functions = [
            exp.name.decode("utf-8")
            for exp in test_binary.DIRECTORY_ENTRY_EXPORT.symbols
            if hasattr(exp, "name") and hasattr(exp.name, "decode")
        ]
    except AttributeError:
        raise AttributeError("Unable to collect EXPORTS from PEFile: {}".format(filepath.name))
    finally:
        test_binary.close()

    return exported_functions


def process_handles_output_schema(handle):
    handle_type_map = {
        "Index": is_numeric_type,
        "AccessMask": is_numeric_type,
        "ObjectAddress": is_numeric_type,
        "Type": is_string_type,
    }
    if "Name" in handle:
        handle_type_map["Name"] = is_string_type
    # Turns out that based on the implementation, these don't have to be reported in results, making them optional for
    # each handle to process
    if "HandleCount" in handle or "PointerCount" in handle:
        handle_type_map["HandleCount"] = is_numeric_type
        handle_type_map["PointerCount"] = is_numeric_type

    return return_section_schema_checks(
        section=handle, type_mapping=handle_type_map, required_keys=handle_type_map.keys()
    )


def check_schema_handles_in_proc(handle_list):
    handles_schema_failures = []
    for handle in handle_list:
        schema_failure = process_handles_output_schema(handle)
        if schema_failure:
            handles_schema_failures.append(schema_failure)
    assert (
        not handles_schema_failures
    ), f"Found handles issues: {pprint_base_formatter(handles_schema_failures)}"


def validate_handles_not_missing(expected_handles, process, handle_list=None):
    """
    :param handle_list: specific handle list, not required, and if None retrieve from the process result
    :param expected_handles: dict of the expected handles and their types
    :param process: audit result which should have a HandleList section to validate

    """
    if handle_list:
        named_audit_handles = [handle for handle in handle_list if "Name" in handle]
    else:
        named_audit_handles = [handle for handle in process["HandleList"] if "Name" in handle]

    handles_found = frozenset(
        sfkey
        for handle in named_audit_handles
        for sfkey, sfval in expected_handles.items()
        if handle["Name"] == sfval and handle["Type"] == sfkey
    )
    context = {"Process Name": process["name"], "Handles found": process["HandleList"]}
    missing_handles = list(set(expected_handles.keys()) - set(handles_found))
    assert not missing_handles, pprint_missing_fields_failure(missing_handles, context)