import frappe


def create_api_log(
    transaction_id,
    event_type,
    integration_type,
    endpoint,
    request_data,
    response_data,
    http_status=200,
    success=True,
    error_message=None
):

    log = frappe.get_doc({

        "doctype": "API Integration Log",

        "transaction_id": transaction_id,

        "event_type": event_type,

        "integration_type": integration_type,

        "endpoint": endpoint,

        "request_data": request_data,

        "response_data": response_data,

        "http_status": http_status,

        "success": 1 if success else 0,

        "error_message": error_message,

        "timestamp": frappe.utils.now()
    })

    log.insert(
        ignore_permissions=True
    )

    return log.name