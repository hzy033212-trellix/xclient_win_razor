import pprint


def pprint_base_formatter(object_to_print):
    return pprint.pformat(object_to_print, indent=2, width=120)


def pprint_missing_fields_failure(missing, object_to_print):
    return (
        "Found missing fields in the section: \n"
        "Missing Fields: {}, \n"
        "Process infomation: \n\t{}".format(missing, pprint_base_formatter(object_to_print))
    )


def pprint_comparison_field_failure(found, expected):
    return (
        "Expected values don't match the values found in the result: \n"
        "Found value: {}\n"
        "Expected value: \n\t{}".format(pprint_base_formatter(found), pprint_base_formatter(expected))
    )


def pprint_type_mismatch_field_failure(mismatches, context=None):
    failure_string = "Mismatched types found in section: \n" "Details: {}".format(
        pprint.pformat(mismatches, indent=2, width=120)
    )
    if context:
        failure_string += "\nContext:\n{}".format(pprint.pformat(context, indent=2, width=120))
    return failure_string


def pprint_event_capture_failure_context(expected_event, initial_string=None):
    if initial_string:
        assertion_string = initial_string
    else:
        assertion_string = "Event not found in agent audit results, expected: "
    assertion_string += f"\n{pprint_base_formatter(expected_event)}"
    return assertion_string
