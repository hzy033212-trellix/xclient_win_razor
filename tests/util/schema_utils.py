import copy

from tests.util.string_formatting_utils import (
    pprint_missing_fields_failure,
    pprint_type_mismatch_field_failure,
)


def return_missing_fields_in_section(section, required_fields):
    return [field for field in required_fields if field not in section]


def return_type_mismatches(key_val_dict, key_type_func_dict):
    type_mismatches = []
    # Check to make sure that the key_type_func_dict keys are in the key_val_dict
    missing_fields = return_missing_fields_in_section(key_val_dict, key_val_dict.keys())
    if missing_fields:
        raise KeyError(
            "The dictionary which contains type checks cannot have keys "
            "which are not in the section for type checking, found: {}".format(missing_fields)
        )
    for key, val in key_val_dict.items():
        # This if is in place to allow passing through a section of the audit without having to
        # TODO: add in the ability to parse the lists of items
        if key in key_type_func_dict:
            if not key_type_func_dict[key](val):
                type_mismatches.append({"key": key, "val": val, "found_type": type(val)})
    return type_mismatches


def return_section_schema_checks(
    section,
    type_mapping=None,
    required_keys=None,
    output_keys_to_exclude=None,
):
    section_results = {}

    copy_section = copy.deepcopy(section)
    if output_keys_to_exclude:
        for key in output_keys_to_exclude:
            copy_section.pop(key, None)
    if required_keys:
        missing = return_missing_fields_in_section(section, required_keys)
        if missing:
            section_results["missing_fields"] = pprint_missing_fields_failure(missing, copy_section)
    if type_mapping:
        mismatches = return_type_mismatches(section, type_mapping)
        if mismatches:
            section_results["field_type_mismatch"] = pprint_type_mismatch_field_failure(
                mismatches, copy_section
            )

    return section_results