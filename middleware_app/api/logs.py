import uuid
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
    log_name = f"API-{uuid.uuid4().hex[:12].upper()}"

    req_payload = request_data if isinstance(request_data, str) else frappe.as_json(request_data)
    res_payload = response_data if isinstance(response_data, str) else frappe.as_json(response_data)

    log = frappe.get_doc({
        "doctype": "API Integration Log",
        "name": log_name,
        "transaction_id": transaction_id,
        "event_type": event_type,
        "integration_type": integration_type,
        "endpoint": endpoint,
        "request_data": req_payload,
        "response_data": res_payload,
        "http_status": http_status,
        "success": success,
        "error_message": error_message
    })

    log.insert(
        ignore_permissions=True,
        set_name=log_name
    )

    frappe.db.commit()
    return log.name