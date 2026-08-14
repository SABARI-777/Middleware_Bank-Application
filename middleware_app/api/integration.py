import frappe


@frappe.whitelist(allow_guest=True)
def receive_order():

    data = frappe.request.get_json()

    if not data:
        return {
            "status": "failed",
            "error_code": "EMPTY_REQUEST",
            "message": "Request body is empty"
        }

    required_fields = [
        "order_id",
        "customer_id",
        "item_code",
        "quantity",
        "rate",
        "amount"
    ]

    missing_fields = []

    for field in required_fields:

        if field not in data:
            missing_fields.append(field)

    if missing_fields:

        return {
            "status": "failed",
            "error_code": "MISSING_FIELDS",
            "missing_fields": missing_fields,
            "message": "Required fields are missing"
        }

    return {
        "status": "success",
        "message": "Order received successfully",
        "received_data": data
    }