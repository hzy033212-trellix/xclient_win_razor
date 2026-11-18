from tests.util.string_formatting_utils import pprint_base_formatter
from tests.util.schema_utils import return_section_schema_checks
from tests.util.type_utils import (
    is_string_type,
    is_numeric_type,
    is_collection_string_type,
    is_iso_8601_time_type,
    is_pe_hash_type,
)


def process_digital_signature_output_schema(digital_section):
    # TODO: make very conditional validation logic here
    # signed_description = "The file is signed and the signature was verified."
    dig_sig_type_map = {
        "SignatureExists": is_string_type,
        "SignatureVerified": is_string_type,
        "Description": is_string_type,
    }
    if (
        digital_section["SignatureExists"] == "true"
        and digital_section["SignatureVerified"] == "true"
    ):
        dig_sig_type_map["CertificateSubject"] = is_string_type
        dig_sig_type_map["CertificateIssuer"] = is_string_type

    return return_section_schema_checks(
        section=digital_section,
        type_mapping=dig_sig_type_map,
        required_keys=dig_sig_type_map.keys(),
    )


def process_device_item_output_schema(device_section):
    # TODO: allow this to be flexible, research what is truly "required" or how to eval whether
    # TODO: certain other fields should be included
    # signed_description = "The file is signed and the signature was verified."
    device_type_map = {
        "DeviceObject": is_numeric_type,
        "AttachedDeviceObject": is_numeric_type,
        "AttachedDriverObject": is_numeric_type,
        "AttachedDriverName": is_string_type,
        "AttachedToDeviceObject": is_numeric_type,
        "AttachedToDriverObject": is_numeric_type,
        "AttachedToDriverName": is_string_type,
    }
    return return_section_schema_checks(
        section=device_section, type_mapping=device_type_map, required_keys=device_type_map.keys()
    )


def process_exports_output_schema(export):

    export_type_map = {
        "NumberOfFunctions": is_numeric_type,
        "NumberOfNames": is_numeric_type,
        "DllName": is_string_type,
        "ExportedFunctions": is_collection_string_type,
    }
    # It's kinda redundant to check these here, but I don't have anything DRY-er right now
    if "ExportsTimeStamp" in export:
        export_type_map["ExportsTimeStamp"] = is_iso_8601_time_type
    if "ExportTSHash" in export:
        export_type_map["ExportTSHash"] = is_pe_hash_type

    exports_results = return_section_schema_checks(
        section=export,
        type_mapping=export_type_map,
        required_keys=export_type_map.keys(),
        output_keys_to_exclude=["ExportedFunctions"],
    )
    return exports_results


def process_imported_modules_output_schema(imported_modules):
    import_results = {}
    import_type_map = {
        "Name": is_string_type,
        "NumberOfFunctions": is_numeric_type,
        "ImportedFunctions": is_collection_string_type,
    }
    unaccounted_module_results = []
    for module in imported_modules:
        module_results = return_section_schema_checks(
            section=module,
            type_mapping=import_type_map,
            required_keys=import_type_map.keys(),
            output_keys_to_exclude=["ImportedFunctions"],
        )
        if module_results and "Name" in module:
            import_results[module["Name"]] = module_results
        elif module_results:
            unaccounted_module_results.append(module_results)
    if unaccounted_module_results:
        import_results["unaccounted_modules"] = pprint_base_formatter(unaccounted_module_results)
    return import_results