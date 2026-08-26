import hashlib
import json
import random
import requests
import frappe
from frappe.utils import flt, now
from middleware_app.api.logs import create_api_log


def generate_otp():
    return str(random.randint(100000, 999999))


def hash_otp(otp):
    return hashlib.sha256(str(otp).encode()).hexdigest()


def send_otp_sms(mobile, otp):
    message = f"Your payment OTP is {otp}. Do not share this OTP with anyone."
    frappe.logger().info(f"SMS Dispatch -> {mobile}: {message}")
    return True

def save_otp_failure_to_erp(
    otp_verification_id,
    invoices,
    error,
    otp_entered,
    mobile,
    attempt_no
):
    ERP_URL = (
        "http://erp.site:8000"
        "/api/method/intial_app.api.payment.save_otp_failure"
    )

    api_key = frappe.conf.get("payment_erp_api_key")
    api_secret = frappe.conf.get("payment_erp_api_secret")

    if not api_key or not api_secret:
        frappe.log_error(
            "ERP API credentials missing in site_config.",
            "OTP Failure ERP Sync"
        )
        return

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }

    for invoice_data in invoices:

        invoice_id = invoice_data.get("invoice_id")

        if not invoice_id:
            continue

        payload = {
            "invoice_id": invoice_id,
            "ref_no": otp_verification_id,
            "error": error,
            "otp_entered": otp_entered,
            "mobile": mobile,
            "attempt_no": attempt_no
        }

        print("THIS IS FROM MID OTP SAVE:", payload)

        try:

            response = requests.post(
                ERP_URL,
                headers=headers,
                json=payload,
                timeout=20
            )

            print(
                "ERP OTP FAILURE STATUS:",
                response.status_code
            )

            print(
                "ERP OTP FAILURE RESPONSE:",
                response.text
            )

            if response.status_code != 200:
                frappe.log_error(
                    f"""
                    Invoice: {invoice_id}

                    HTTP Status:
                    {response.status_code}

                    Response:
                    {response.text}

                    Payload:
                    {frappe.as_json(payload)}
                    """,
                    f"OTP Failure ERP Sync Failed - {invoice_id}"
                )

        except Exception:

            frappe.log_error(
                frappe.get_traceback(),
                f"OTP Failure ERP Sync Exception - {invoice_id}"
            )
def save_single_otp_failure_to_erp(
    otp_verification_id,
    invoice_id,
    error,
    otp_entered,
    mobile,
    attempt_no
):
    ERP_URL = (
        "http://erp.site:8000"
        "/api/method/intial_app.api.payment.save_otp_failure"
    )

    api_key = frappe.conf.get("payment_erp_api_key")
    api_secret = frappe.conf.get("payment_erp_api_secret")

    if not api_key or not api_secret:
        frappe.log_error(
            "ERP API credentials missing in site_config.",
            "Single OTP Failure ERP Sync"
        )
        return

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }

    payload = {
        "invoice_id": invoice_id,
        "ref_no": otp_verification_id,
        "error": error,
        "otp_entered": otp_entered,
        "mobile": mobile,
        "attempt_no": attempt_no
    }

    print("SINGLE OTP FAILURE:", payload)

    try:

        response = requests.post(
            ERP_URL,
            headers=headers,
            json=payload,
            timeout=20
        )

        print(
            "ERP SINGLE OTP FAILURE STATUS:",
            response.status_code
        )

        print(
            "ERP SINGLE OTP FAILURE RESPONSE:",
            response.text
        )

        if response.status_code != 200:
            frappe.log_error(
                f"""
                Invoice: {invoice_id}

                Status:
                {response.status_code}

                Response:
                {response.text}

                Payload:
                {frappe.as_json(payload)}
                """,
                f"Single OTP Failure ERP Sync Failed - {invoice_id}"
            )

    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            f"Single OTP Failure ERP Sync Exception - {invoice_id}"
        )

@frappe.whitelist(allow_guest=True)
def request_otp(mobile):
    if not mobile:
        frappe.throw("Mobile number is required.")

    otp = generate_otp()
    print(otp)
    otp_hash_value = hash_otp(otp)

    verification = frappe.get_doc({
        "doctype": "OTP Verification",
        "mobile": mobile,
        "otp_hash": otp_hash_value,
        "attempt_count": 0,
        "status": "Pending",
        "created_at": now()
    })
    verification.insert(ignore_permissions=True)

    send_otp_sms(mobile, otp)

    response_data = {
        "success": True,
        "otp_verification_id": verification.name,
        "message": "OTP dispatched successfully."
    }

    try:
        create_api_log(
            transaction_id=verification.name,
            event_type="GENERATE_OTP",
            integration_type="ERP → Middleware",
            endpoint="/api/method/middleware_app.api.payment.request_otp",
            request_data={"mobile": mobile},
            response_data=response_data,
            http_status=200,
            success=True
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"API Log Failed - OTP Request {verification.name}")

    return response_data


@frappe.whitelist(allow_guest=True)
def verify_otp(
    otp_verification_id,
    otp,
    invoice_id=None,
    mobile=None,
    install_no=None,
    receiver_bank_account=None,
    receiver_account_number=None,
    mode_of_payment=None,
    sender_account=None
):
    if not otp_verification_id or not otp:
        frappe.throw("OTP Verification ID and OTP are required.")

    try:
        verification = frappe.get_doc("OTP Verification", otp_verification_id)
    except frappe.DoesNotExistError:
        return {"success": False, "message": "OTP Verification record not found."}

    if verification.status == "Verified":
        return {"success": False, "message": "OTP is already verified."}

    if verification.attempt_count >= 3:
        return {
            "success": False,
            "max_attempts": True,
            "attempt_count": verification.attempt_count,
            "message": "Maximum 3 OTP attempts exceeded."
        }

    entered_hash = hash_otp(otp)

    if entered_hash != verification.otp_hash:
        verification.attempt_count += 1
        if verification.attempt_count >= 3:
            verification.status = "Failed"
        verification.save(ignore_permissions=True)

        save_single_otp_failure_to_erp(
            otp_verification_id=otp_verification_id,
            invoice_id=invoice_id,
            error="Invalid OTP entered.",
            otp_entered=otp,
            mobile=mobile or verification.mobile,
            attempt_no=verification.attempt_count
    )
        response_data = {
            "success": False,
            "otp_verification_id": otp_verification_id,
            "attempt_count": verification.attempt_count,
            "max_attempts": verification.attempt_count >= 3,
            "message": "Invalid OTP entered."
        }

        try:
            create_api_log(
                transaction_id=otp_verification_id,
                event_type="VERIFY_OTP",
                integration_type="ERP → Middleware",
                endpoint="/api/method/middleware_app.api.payment.verify_otp",
                request_data={"otp_verification_id": otp_verification_id, "attempt": verification.attempt_count},
                response_data=response_data,
                http_status=200,
                success=False,
                error_message="OTP Mismatch"
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"API Log Failed - OTP Mismatch {otp_verification_id}")

        return response_data

    transaction = frappe.get_doc({
        "doctype": "Payment Transaction",
        "erp_invoice": invoice_id,
        "install_no": install_no,
        "mobile": mobile or verification.mobile,
        "amount": 0.0,
        "currency": "INR",
        "payment_status": "Pending",
        "custom_initiation_status": "Not Initiated",
        "custom_sender_account": sender_account,
        "custom_receiver_bank_account": receiver_bank_account,
        "custom_receiver_account_number": receiver_account_number,
        "custom_mode_of_payment": mode_of_payment
    })
    transaction.insert(ignore_permissions=True)

 
    create_pi_pending_entry(
        transaction,
        otp_verification_id
    )

    

    verification.status = "Verified"
    verification.verified_at = now()
    verification.transaction_id = transaction.name
    verification.save(ignore_permissions=True)

    response_data = {
        "success": True,
        "otp_verification_id": otp_verification_id,
        "transaction_id": transaction.name,
        "message": "OTP verified. Payment transaction initiated."
    }

    try:
        create_api_log(
            transaction_id=transaction.name,
            event_type="VERIFY_OTP",
            integration_type="ERP → Middleware",
            endpoint="/api/method/middleware_app.api.payment.verify_otp",
            request_data={"otp_verification_id": otp_verification_id},
            response_data=response_data,
            http_status=200,
            success=True
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"API Log Failed - OTP Verify {transaction.name}")

    return response_data


@frappe.whitelist(allow_guest=True)
def verify_bulk_otp(otp_verification_id, otp, invoices, mobile=None):
    if not otp_verification_id or not otp:
        frappe.throw("OTP Verification ID and OTP are required.")

    if not invoices:
        frappe.throw("Purchase Invoices are required.")

    if isinstance(invoices, str):
        invoices = frappe.parse_json(invoices)

    if not isinstance(invoices, list):
        frappe.throw("Invoices must be a list.")

    try:
        verification = frappe.get_doc("OTP Verification", otp_verification_id)
    except frappe.DoesNotExistError:
        return {"success": False, "message": "OTP Verification record not found."}

    if verification.status == "Verified":
        return {"success": False, "message": "OTP is already verified."}

    if verification.attempt_count >= 3:
        return {
            "success": False,
            "max_attempts": True,
            "attempt_count": verification.attempt_count,
            "message": "Maximum 3 OTP attempts exceeded."
        }

    entered_hash = hash_otp(otp)

    if entered_hash != verification.otp_hash:

        verification.attempt_count += 1

        if verification.attempt_count >= 3:
            verification.status = "Failed"

        verification.save(
            ignore_permissions=True
        )

        save_otp_failure_to_erp(
            otp_verification_id=otp_verification_id,
            invoices=invoices,
            error="Invalid OTP entered.",
            otp_entered=otp,
            mobile=mobile or verification.mobile,
            attempt_no=verification.attempt_count
        )

        response_data = {
            "success": False,
            "otp_verification_id": otp_verification_id,
            "attempt_count": verification.attempt_count,
            "max_attempts": verification.attempt_count >= 3,
            "message": "Invalid OTP entered."
        }

        return response_data

    transactions = []

    for invoice_data in invoices:
        invoice_id = invoice_data.get("invoice_id")
        install_no = invoice_data.get("install_no")
        amount = flt(invoice_data.get("amount") or 0)
        receiver_bank_account = invoice_data.get("receiver_bank_account")
        receiver_account_number = invoice_data.get("receiver_account_number")
        mode_of_payment = invoice_data.get("mode_of_payment")
        sender_account = invoice_data.get("sender_account")

        if not invoice_id:
            frappe.throw("Purchase Invoice ID is required.")

        if amount <= 0:
            frappe.throw(f"Payment amount for {invoice_id} must be greater than zero.")

       
        transaction = frappe.get_doc({
            "doctype": "Payment Transaction",
            "erp_invoice": invoice_id,
            "install_no": install_no,
            "mobile": mobile or verification.mobile,
            "amount": amount,
            "currency": "INR",
            "payment_status": "Pending",
            "custom_initiation_status": "Not Initiated",
            "custom_sender_account": sender_account,
            "custom_receiver_bank_account": receiver_bank_account,
            "custom_receiver_account_number": receiver_account_number,
            "custom_mode_of_payment": mode_of_payment
        })
        transaction.insert(ignore_permissions=True)

        create_pi_pending_entry(
            transaction,
            otp_verification_id
        )

        transactions.append({
            "invoice_id": invoice_id,
            "transaction_id": transaction.name,
            "install_no": install_no,
            "amount": amount
        })

    verification.status = "Verified"
    verification.verified_at = now()
    if transactions:
        verification.transaction_id = transactions[0]["transaction_id"]
    verification.save(ignore_permissions=True)

    response_data = {
        "success": True,
        "otp_verification_id": otp_verification_id,
        "transactions": transactions,
        "message": (
        "OTP verified. "
        "Payment transaction created and waiting for initiation."
    )
    }

    try:
        create_api_log(
            transaction_id=otp_verification_id,
            event_type="VERIFY_BULK_OTP",
            integration_type="ERP → Middleware",
            endpoint="/api/method/middleware_app.api.payment.verify_bulk_otp",
            request_data={
                "otp_verification_id": otp_verification_id,
                "invoice_count": len(invoices)
            },
            response_data=response_data,
            http_status=200,
            success=True
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "API Log Failed - Bulk OTP Verify")

    return response_data

def create_pi_pending_entry(transaction, otp_verification_id):

    ERP_URL = (
        "http://erp.site:8000"
        "/api/method/intial_app.api.payment.create_processing_payment"
    )

    api_key = frappe.conf.get("payment_erp_api_key")
    api_secret = frappe.conf.get("payment_erp_api_secret")

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }

    payload = {
        "invoice_id": transaction.erp_invoice,
        "amount": transaction.amount,
        "mobile": transaction.mobile,
        "transaction_id": transaction.name,
        "sender_account": transaction.custom_sender_account,
        "mode_of_payment": transaction.custom_mode_of_payment,
        "otp_verification_id": otp_verification_id
    }

    response = requests.post(
        ERP_URL,
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code != 200:
        frappe.throw(
            f"ERP PI Pending Entry Failed: {response.text}"
        )

    result = response.json().get("message")

    if not result or not result.get("success"):
        frappe.throw(
            "Failed to create Purchase Invoice payment entry."
        )

    return result

def mock_bank_initiate_payment(transaction_id, account_number, amount, mode_of_payment, sender_account, mobile):
    sender_account_number = ''.join(filter(str.isdigit, mobile or ""))[-10:]

    doc_name = frappe.db.get_value(
        "Bank Information",
        {
            "bank_name": sender_account,
            "account_number": sender_account_number
        },
        "name"
    )

    if not doc_name:
        frappe.throw(f"Bank Information not configured for {sender_account}.")

    bank_info = frappe.get_doc("Bank Information", doc_name)
    url = bank_info.initiate_url
    api_key = bank_info.api_key
    api_secret = bank_info.api_secret

    if not url or not api_key or not api_secret:
        frappe.throw("Mock Bank API configuration is incomplete.")

    mode = str(mode_of_payment).upper()
    if mode not in ["NEFT", "RTGS", "IMPS", "UPI"]:
        frappe.throw("Invalid mode of payment. Allowed: NEFT, RTGS, IMPS, UPI")

    payload = {
        "unique_id": transaction_id,
        "account_number": account_number,
        "payment_status": "COMPLETED",
        "mode_of_payment": mode,
        "amount": float(amount)
    }

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        frappe.log_error(frappe.get_traceback(), f"Mock Bank Network Error - {transaction_id}")
        raise Exception(f"Unable to connect to Mock Bank: {str(e)}")

    try:
        result = response.json()
    except Exception:
        result = {"response_message": response.text}

    try:
        create_api_log(
            transaction_id=transaction_id,
            event_type="PROCESS_PAYMENT",
            integration_type="Middleware → Bank",
            endpoint=url,
            request_data=payload,
            response_data=result,
            http_status=response.status_code,
            success=response.status_code in [200, 202],
            error_message=(
                result.get("response_message")
                if response.status_code not in [200, 202]
                else None
            )
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"API Log Failed - Bank Initiate {transaction_id}")

    return {
        "success": response.status_code in [200, 202],
        "http_status": response.status_code,
        "status": result.get("payment_status"),
        "transaction_id": result.get("transaction_id"),
        "amount": result.get("amount", amount),
        "response_code": result.get("response_code"),
        "message": result.get("response_message"),
        "raw_response": result
    }

def get_payment_status_from_bank(transaction):
    sender_account = transaction.custom_sender_account
    mobile = transaction.mobile

    sender_account_number = ''.join(filter(str.isdigit, mobile or ""))[-10:]

    doc_name = frappe.db.get_value(
        "Bank Information",
        {
            "bank_name": sender_account,
            "account_number": sender_account_number
        },
        "name"
    )

    if not doc_name:
        frappe.log_error(f"Bank Information not found for {sender_account}", "Bank Information Lookup")
        return None

    bank_info = frappe.get_doc("Bank Information", doc_name)
    url = bank_info.status_url
    api_key = bank_info.api_key
    api_secret = bank_info.api_secret

    if not url or not api_key or not api_secret:
        return None

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    request_data = {"unique_id": transaction.name}

    try:
        response = requests.post(url, headers=headers, json=request_data, timeout=30)
        try:
            result = response.json()
        except Exception:
            result = {"response_message": response.text}

        try:
            create_api_log(
                transaction_id=transaction.name,
                event_type="PAYMENT_STATUS",
                integration_type="Middleware → Bank",
                endpoint=url,
                request_data=request_data,
                response_data=result,
                http_status=response.status_code,
                success=response.status_code in [200, 202],
                error_message=(
                    result.get("response_message")
                    if response.status_code not in [200, 202]
                    else None
                )
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"API Log Failed - Bank Status Polling {transaction.name}")

        return result if response.status_code in [200, 202] else None

    except Exception as e:
        try:
            create_api_log(
                transaction_id=transaction.name,
                event_type="PAYMENT_STATUS",
                integration_type="Middleware → Bank",
                endpoint=url,
                request_data=request_data,
                response_data={"error": str(e)},
                http_status=500,
                success=False,
                error_message=str(e)
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"API Log Failed - Network Failure {transaction.name}")

        frappe.log_error(frappe.get_traceback(), f"Bank Polling Network Failure - {transaction.name}")
        return None


def handle_pending_success(transaction, result, request_id):
    bank_reference = result.get("transaction_id")
    payload = {
        "invoice_id": transaction.erp_invoice,
        "transaction_id": transaction.name,
        "install_no": transaction.install_no,
        "amount": transaction.amount,
        "mobile": transaction.mobile,
        "status": "SUCCESS",
        "bank_reference": bank_reference,
        "sender_account": transaction.custom_sender_account,
        "mode_of_payment": transaction.custom_mode_of_payment
    }

    ERP_URL = "http://erp.site:8000/api/method/intial_app.api.payment.save_payment_result"
    api_key = frappe.conf.get("payment_erp_api_key")
    api_secret = frappe.conf.get("payment_erp_api_secret")

    if not api_key or not api_secret:
        frappe.log_error(
            "ERP API credentials are missing.",
            f"ERP Payment Sync Failed - {transaction.name}"
        )
        return False

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(ERP_URL, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            frappe.log_error(
                f"HTTP Status: {response.status_code}\nResponse: {response.text}\nPayload: {frappe.as_json(payload)}",
                f"ERP Payment Sync Failed - {transaction.name}"
            )
            return False

        try:
            response_data = response.json()
        except Exception:
            frappe.log_error(
                f"ERP returned invalid JSON.\nResponse: {response.text}\nPayload: {frappe.as_json(payload)}",
                f"ERP Invalid Response - {transaction.name}"
            )
            return False

        message = response_data.get("message")
        if not message or not message.get("success"):
            frappe.log_error(
                f"ERP returned success=False.\nResponse: {response.text}\nPayload: {frappe.as_json(payload)}",
                f"ERP Payment Sync Failed - {transaction.name}"
            )
            return False

        frappe.db.set_value(
            "Payment Transaction",
            transaction.name,
            {
                "payment_status": "Success",
                "bank_reference": bank_reference,
                "processed_at": now()
            }
        )
        frappe.db.commit()
        return True

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"ERP Payment Sync Exception - {transaction.name}"
        )
        return False


def handle_pending_failure(transaction, result, request_id):
    failure_reason = result.get("response_message") or "Bank declined payment."
    bank_reference = result.get("transaction_id")

    payload = {
        "invoice_id": transaction.erp_invoice,
        "transaction_id": transaction.name,
        "install_no": transaction.install_no,
        "amount": transaction.amount,
        "mobile": transaction.mobile,
        "status": "FAILED",
        "bank_reference": bank_reference,
        "failure_reason": failure_reason,
        "sender_account": transaction.custom_sender_account,
        "mode_of_payment": transaction.custom_mode_of_payment
    }

    ERP_URL = "http://erp.site:8000/api/method/intial_app.api.payment.save_payment_result"
    api_key = frappe.conf.get("payment_erp_api_key")
    api_secret = frappe.conf.get("payment_erp_api_secret")

    if not api_key or not api_secret:
        frappe.log_error(
            "ERP API key or secret is missing.",
            f"ERP Failure Sync - {transaction.name}"
        )
        return False

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(ERP_URL, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            frappe.log_error(
                f"ERP Failure Sync Failed\nTransaction: {transaction.name}\nHTTP Status: {response.status_code}\nERP Response: {response.text}\nPayload: {frappe.as_json(payload)}",
                f"ERP Failure Sync - {transaction.name}"
            )
            return False

        try:
            response_data = response.json()
        except Exception:
            frappe.log_error(
                f"ERP returned invalid JSON.\nTransaction: {transaction.name}\nResponse: {response.text}",
                f"ERP Invalid Failure Response - {transaction.name}"
            )
            return False

        message = response_data.get("message")
        if not message or not message.get("success"):
            frappe.log_error(
                f"ERP returned success=False.\nTransaction: {transaction.name}\nResponse: {response.text}",
                f"ERP Failure Sync - {transaction.name}"
            )
            return False

        frappe.db.set_value(
            "Payment Transaction",
            transaction.name,
            {
                "payment_status": "Failed",
                "bank_reference": bank_reference,
                "failure_reason": failure_reason,
                "processed_at": now()
            }
        )
        frappe.db.commit()
        return True

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"ERP Sync Failure on Rejection - {transaction.name}"
        )
        return False

@frappe.whitelist()
def check_pending_payments():

    lock_key = "middleware_payment_checker_lock"

    if frappe.cache().get_value(lock_key):

        return {
            "success": True,
            "message": (
                "Payment checker is already running. "
                "Skipping run."
            ),
            "skipped": True
        }

    frappe.cache().set_value(
        lock_key,
        "1",
        expires_in_sec=240
    )

    try:

        pending_transactions = frappe.get_all(
            "Payment Transaction",
            filters={
                "payment_status": "Pending",
                "custom_initiation_status": "Initiated",
                "amount": [">", 0]
            },
            fields=[
                "name",
                "erp_invoice",
                "install_no",
                "amount",
                "mobile",
                "custom_receiver_bank_account",
                "custom_sender_account",
                "custom_mode_of_payment"
            ],
            order_by="creation asc"
        )

        total_pending = len(
            pending_transactions
        )

        processed = 0
        failed = 0
        no_response = 0

        for transaction in pending_transactions:

            try:

                result = get_payment_status_from_bank(
                    transaction
                )

                if not result:
                    no_response += 1
                    continue

                request_id = transaction.name

                status = str(
                    result.get("payment_status")
                    or result.get("status")
                    or ""
                ).upper()


                if status == "PENDING":
                    continue
                elif status in (
                    "COMPLETED",
                    "SUCCESS"
                ):

                    if handle_pending_success(
                        transaction,
                        result,
                        request_id
                    ):
                        processed += 1
                    else:
                        failed += 1
                elif status in (
                    "FAILED",
                    "REJECTED",
                    "ERROR",
                    "FAILURE"
                ):

                    if handle_pending_failure(
                        transaction,
                        result,
                        request_id
                    ):
                        processed += 1
                    else:
                        failed += 1

                else:

                    failed += 1

                    frappe.log_error(
                        frappe.as_json(result),
                        (
                            "Unknown Payment Status - "
                            f"{transaction.name}"
                        )
                    )

            except Exception:

                failed += 1

                frappe.log_error(
                    frappe.get_traceback(),
                    (
                        "Pending Polling Loop Error - "
                        f"{transaction.name}"
                    )
                )

        frappe.db.commit()

        return {
            "success": True,
            "message": (
                "Pending payment check completed."
            ),
            "total_pending": total_pending,
            "processed": processed,
            "no_bank_response": no_response,
            "failed": failed
        }

    finally:

        frappe.cache().delete_value(
            lock_key
        )
@frappe.whitelist()
def initiate_payment(transaction_id):

    if not transaction_id:
        frappe.throw("Payment Transaction ID is required.")

   
    try:
        transaction = frappe.get_doc(
            "Payment Transaction",
            transaction_id
        )
    except frappe.DoesNotExistError:
        frappe.throw(
            f"Payment Transaction {transaction_id} not found."
        )

    if transaction.payment_status != "Pending":
        return {
            "success": False,
            "status": transaction.payment_status,
            "transaction_id": transaction.name,
            "message": (
                "Payment Transaction is not Pending."
            )
        }

    if transaction.custom_initiation_status != "Not Initiated":
        return {
            "success": False,
            "status": "ALREADY_INITIATED",
            "transaction_id": transaction.name,
            "message": (
                "Payment Transaction is already initiated."
            )
        }

    amount = flt(transaction.amount)
    mobile = transaction.mobile

    sender_account = (
        transaction.custom_sender_account
    )

    receiver_account_number = (
        transaction.custom_receiver_account_number
    )

    mode_of_payment = (
        transaction.custom_mode_of_payment
    )


    if amount <= 0:
        frappe.throw(
            "Payment amount must be greater than zero."
        )

    if not sender_account:
        frappe.throw(
            "Sender Account is missing."
        )

    if not receiver_account_number:
        frappe.throw(
            "Receiver Account Number is missing."
        )

    if not mode_of_payment:
        frappe.throw(
            "Mode of Payment is missing."
        )

    try:

        bank_result = mock_bank_initiate_payment(
            transaction_id=transaction.name,
            account_number=receiver_account_number,
            amount=amount,
            mode_of_payment=mode_of_payment,
            sender_account=sender_account,
            mobile=mobile
        )

    except Exception as e:


        transaction.db_set(
            "payment_status",
            "Failed",
            update_modified=True
        )

        transaction.db_set(
            "failure_reason",
            str(e),
            update_modified=True
        )

        transaction.db_set(
            "processed_at",
            now(),
            update_modified=True
        )

        frappe.db.commit()

        return {
            "success": False,
            "status": "FAILED",
            "transaction_id": transaction.name,
            "failure_reason": str(e),
            "message": "Bank initiation failed."
        }

    bank_status = str(
        bank_result.get("status")
        or bank_result.get("payment_status")
        or ""
    ).strip().upper()

    bank_reference = (
        bank_result.get("transaction_id")
        or bank_result.get("bank_reference")
    )

    failure_reason = (
        bank_result.get("failure_reason")
        or bank_result.get("response_message")
        or bank_result.get("message")
        or "Bank declined payment."
    )


    if bank_status in (
        "FAILED",
        "FAILURE",
        "REJECTED",
        "ERROR"
    ):

        transaction.db_set(
            "payment_status",
            "Failed",
            update_modified=True
        )

        transaction.db_set(
            "failure_reason",
            failure_reason,
            update_modified=True
        )

        transaction.db_set(
            "bank_reference",
            bank_reference,
            update_modified=True
        )

        transaction.db_set(
            "processed_at",
            now(),
            update_modified=True
        )

        frappe.db.commit()

        return {
            "success": False,
            "status": "FAILED",
            "transaction_id": transaction.name,
            "bank_reference": bank_reference,
            "failure_reason": failure_reason
        }

    if bank_status in (
        "PENDING",
        "COMPLETED",
        "SUCCESS"
    ):

        transaction.db_set(
            "payment_status",
            "Pending",
            update_modified=True
        )

        transaction.db_set(
            "custom_initiation_status",
            "Initiated",
            update_modified=True
        )

        transaction.db_set(
            "bank_reference",
            bank_reference,
            update_modified=True
        )

        transaction.db_set(
            "failure_reason",
            None,
            update_modified=True
        )

        transaction.db_set(
            "processed_at",
            now(),
            update_modified=True
        )

        frappe.db.commit()

        return {
            "success": True,
            "status": "INITIATED",
            "transaction_id": transaction.name,
            "bank_reference": bank_reference,
            "message": (
                "Payment initiated. "
                "Scheduler will check bank status."
            )
        }

    frappe.log_error(
        frappe.as_json(bank_result),
        f"Unknown Bank Initiation Response - {transaction.name}"
    )

    return {
        "success": False,
        "status": "UNKNOWN",
        "transaction_id": transaction.name,
        "message": "Unknown bank response."
    }
@frappe.whitelist()
def initiate_pending_transactions():

    lock_key = "middleware_payment_initiation_lock"

    if frappe.cache().get_value(lock_key):
        return {
            "success": True,
            "skipped": True,
            "message": (
                "Payment initiation scheduler "
                "is already running."
            )
        }

    frappe.cache().set_value(
        lock_key,
        "1",
        expires_in_sec=240
    )

    processed = 0
    failed = 0

    try:

        transactions = frappe.get_all(
            "Payment Transaction",
            filters={
                "payment_status": "Pending",
                "custom_initiation_status": "Not Initiated",
                "amount": [">", 0]
            },
            fields=[
                "name"
            ],
            order_by="creation asc"
        )

        for row in transactions:

            transaction_id = row.name

            try:

                result = initiate_payment(
                    transaction_id=transaction_id
                )

                if result.get("success"):
                    processed += 1
                else:
                    failed += 1

            except Exception:

                failed += 1

                frappe.log_error(
                    frappe.get_traceback(),
                    (
                        "Payment Initiation Scheduler "
                        f"Failed - {transaction_id}"
                    )
                )

        frappe.db.commit()

        return {
            "success": True,
            "processed": processed,
            "failed": failed,
            "message": (
                "Payment initiation scheduler completed."
            )
        }

    finally:

        frappe.cache().delete_value(
            lock_key
        )