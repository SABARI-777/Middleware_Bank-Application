import frappe
import random
import hashlib
import json
import requests
from frappe.utils import now, flt
from middleware_app.api.logs import create_api_log


def generate_otp():
    return str(random.randint(100000, 999999))


def hash_otp(otp):
    return hashlib.sha256(str(otp).encode()).hexdigest()


def send_otp_sms(mobile, otp):
    message = f"Your payment OTP is {otp}. Do not share this OTP with anyone."
    frappe.logger().info(f"SMS Dispatch -> {mobile}: {message}")
    return True


@frappe.whitelist(allow_guest=True)
def request_otp(mobile):
    if not mobile:
        frappe.throw("Mobile number is required.")

    otp = generate_otp()
    print(otp,mobile)
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

    create_api_log(
        transaction_id=verification.name,
        event_type="GENERATE_OTP",
        integration_type="ERP → Middleware",
        endpoint="/api/method/middleware_app.api.payment.request_otp",
        request_data=json.dumps({"mobile": mobile}),
        response_data=json.dumps(response_data),
        http_status=200,
        success=True
    )

    return response_data


@frappe.whitelist(allow_guest=True)
def verify_otp(
    otp_verification_id,
    otp,
    invoice_id=None,
    mobile=None,
    install_no=None,
    receiver_bank_account=None,mode_of_payment=None, sender_account=None
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

        response_data = {
            "success": False,
            "otp_verification_id": otp_verification_id,
            "attempt_count": verification.attempt_count,
            "max_attempts": verification.attempt_count >= 3,
            "message": "Invalid OTP entered."
        }

        create_api_log(
            transaction_id=otp_verification_id,
            event_type="VERIFY_OTP",
            integration_type="ERP → Middleware",
            endpoint="/api/method/middleware_app.api.payment.verify_otp",
            request_data=json.dumps({"otp_verification_id": otp_verification_id, "attempt": verification.attempt_count}),
            response_data=json.dumps(response_data),
            http_status=200,
            success=False,
            error_message="OTP Mismatch"
        )
        return response_data

    transaction = frappe.get_doc({
        "doctype": "Payment Transaction",
        "erp_invoice": invoice_id,
        "install_no": install_no,
        "mobile": mobile or verification.mobile,
        "amount": 0.0,
        "currency": "INR",
        "payment_status": "Pending",
        "custom_sender_account": sender_account,
        "custom_receiver_bank_account": receiver_bank_account,
        "custom_mode_of_payment": mode_of_payment
    })
    transaction.insert(ignore_permissions=True)

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

    create_api_log(
        transaction_id=transaction.name,
        event_type="VERIFY_OTP",
        integration_type="ERP → Middleware",
        endpoint="/api/method/middleware_app.api.payment.verify_otp",
        request_data=json.dumps({"otp_verification_id": otp_verification_id}),
        response_data=json.dumps(response_data),
        http_status=200,
        success=True
    )

    return response_data


def mock_bank_initiate_payment(transaction_id, account_number, amount, mode_of_payment,sender_account,mobile):

     
    sender_account_number = ''.join(filter(str.isdigit, mobile))[-10:]
 
    doc_name = frappe.db.get_value(
    "Bank Information",
    {
        "bank_name": sender_account,
        "account_number": sender_account_number
    },
    "name"
    )

    bank_info = frappe.get_doc("Bank Information", doc_name)

    print(bank_info)
    print('THIS IS BANK INTIATING')

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

    print(payload)
    print(headers)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        frappe.log_error(frappe.get_traceback(), f"Mock Bank Network Error - {transaction_id}")
        raise Exception(f"Unable to connect to Mock Bank: {str(e)}")

    try:
        result = response.json()
    except Exception:
        result = {"response_message": response.text}

    create_api_log(
    transaction_id=transaction_id,
    event_type="PROCESS_PAYMENT",
    integration_type="Middleware → Bank",
    endpoint=url,
    request_data=json.dumps(payload),
    response_data=json.dumps(result),
    http_status=response.status_code,
    success=response.status_code in [200, 202],
    error_message=(
        result.get("response_message")
        if response.status_code not in [200, 202]
        else None
    )
    )

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


@frappe.whitelist(allow_guest=True)
def process_payment(
    transaction_id,
    amount,
    invoice_id=None,
    mobile=None,
    receiver_bank_account=None,
    receiver_account_number=None,
    mode_of_payment=None,
    sender_account=None,
    install_no=None
):
    if not transaction_id:
        return {"success": False, "status": "FAILED", "message": "Transaction ID is required."}

    try:
        transaction = frappe.get_doc("Payment Transaction", transaction_id)
    except frappe.DoesNotExistError:
        return {"success": False, "status": "FAILED", "message": "Payment transaction not found."}

    create_api_log(
        transaction_id=transaction_id,
        event_type="START_PAYMENT",
        integration_type="ERP → Middleware",
        endpoint="/api/method/middleware_app.api.payment.process_payment",
        request_data=json.dumps({
            "transaction_id": transaction_id,
            "amount": amount,
            "invoice_id": invoice_id,
            "mobile": mobile,
            "receiver_bank_account": receiver_bank_account,
            "receiver_account_number": receiver_account_number,
            "mode_of_payment": mode_of_payment,
            "sender_account": sender_account,
            "install_no": install_no
        }),
        response_data=json.dumps({
            "message": "Payment processing started."
        }),
        http_status=200,
        success=True
    )


    if transaction.payment_status == "Success":
        return {
            "success": True,
            "status": "SUCCESS",
            "transaction_id": transaction_id,
            "bank_reference": transaction.bank_reference,
            "amount": transaction.amount,
            "message": "Transaction was already completed."
        }

    transaction.amount = flt(amount)
    transaction.payment_status = "Pending"
    if install_no:
        transaction.install_no = install_no
    transaction.save(ignore_permissions=True)

    try:
        bank_result = mock_bank_initiate_payment(
            transaction_id=transaction_id,
            account_number=receiver_account_number,
            amount=amount,
            mode_of_payment=mode_of_payment,
            sender_account=sender_account,
            mobile=mobile
        )
        print(bank_result)
    except Exception as e:
        transaction.payment_status = "Failed"
        transaction.failure_reason = str(e)
        transaction.processed_at = now()
        transaction.save(ignore_permissions=True)

        return {
            "success": False,
            "status": "FAILED",
            "transaction_id": transaction_id,
            "amount": amount,
            "reason": str(e),
            "message": "Bank gateway connection failed."
        }

    bank_status = str(bank_result.get("status") or "").upper()

    print(bank_status)

    if bank_status == "COMPLETED":
        transaction.payment_status = "Success"
        transaction.bank_reference = bank_result.get("transaction_id")
        transaction.failure_reason = None
        transaction.processed_at = now()
        transaction.save(ignore_permissions=True)

        return {
            "success": True,
            "status": "SUCCESS",
            "transaction_id": transaction_id,
            "amount": amount,
            "bank_reference": transaction.bank_reference,
            "message": "Payment completed successfully."
        }
    
    elif bank_status == "PENDING":
        transaction.payment_status = "Pending"
        transaction.bank_reference = bank_result.get("transaction_id")
        transaction.failure_reason = None
        transaction.save(ignore_permissions=True)

        return {
            "success": True,
            "status": "PENDING",
            "transaction_id": transaction_id,
            "amount": amount,
            "bank_reference": transaction.bank_reference,
            "message": "Payment processing is pending."
        }

    else:
        transaction.payment_status = "Failed"
        transaction.bank_reference = bank_result.get("transaction_id")
        transaction.failure_reason = bank_result.get("message") or "Bank declined payment."
        transaction.processed_at = now()
        transaction.save(ignore_permissions=True)
    

        return {
            "success": False,
            "status": "FAILED",
            "transaction_id": transaction_id,
            "amount": amount,
            "reason": transaction.failure_reason,
            "message": "Payment declined."
        }


def get_payment_status_from_bank(transaction):

    sender_account = transaction.custom_sender_account
    mobile = transaction.mobile

    sender_account_number = ''.join(filter(str.isdigit, mobile))[-10:]

    print("Sender Bank:", sender_account)
    print("Mobile:", mobile)
    print("Account Number:", sender_account_number)

    doc_name = frappe.db.get_value(
        "Bank Information",
        {
            "bank_name": sender_account,
            "account_number": sender_account_number
        },
        "name"
    )

    if not doc_name:
        frappe.log_error(
            f"Bank Information not found\n"
            f"Bank Name: {sender_account}\n"
            f"Account Number: {sender_account_number}\n"
            f"Mobile: {mobile}",
            "Bank Information Lookup"
        )

        # print("Bank Information not found")
        # return None

    bank_info = frappe.get_doc("Bank Information", doc_name)

    print(bank_info.as_dict())
    print("IN CHECKING STATUS")

    url = bank_info.initiate_url
    api_key = bank_info.api_key
    api_secret = bank_info.api_secret

    if not url or not api_key or not api_secret:
        return None

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    request_data = {
    "unique_id": transaction.name
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=request_data,
            timeout=15
        )
        print(response)


        try:
            result = response.json()

        except Exception:
            result = {
                "response_message": response.text
            }



        create_api_log(
            transaction_id=transaction.name,
            event_type="PAYMENT_STATUS",
            integration_type="Middleware → Bank",
            endpoint=url,
            request_data=json.dumps(request_data),
            response_data=json.dumps(result),
            http_status=response.status_code,
            success=response.status_code in [200, 202],
            error_message=(
                result.get("response_message")
                if response.status_code not in [200, 202]
                else None
            )
        )


        if response.status_code in [200, 202]:
            return result


    except Exception as e:

        create_api_log(
            transaction_id=transaction.name,
            event_type="PAYMENT_STATUS",
            integration_type="Middleware → Bank",
            endpoint=url,
            request_data=json.dumps(request_data),
            response_data=json.dumps({
                "error": str(e)
            }),
            http_status=500,
            success=False,
            error_message=str(e)
        )

        frappe.log_error(
            frappe.get_traceback(),
            f"Bank Polling Network Failure - {transaction.name}"
        )

    return result


def handle_pending_success(transaction, result,request_id):

    bank_reference = result.get("transaction_id")

    payload = {
        "invoice_id": transaction.erp_invoice,
        "transaction_id":request_id,
        "amount": transaction.amount,
        "mobile": transaction.mobile,
        "status": "SUCCESS",
        "bank_reference": bank_reference,
        "sender_account": transaction.custom_sender_account,
        "mode_of_payment": transaction.custom_mode_of_payment
    }
    try:
        response = requests.post(
            "http://erp.site:8000/api/method/intial_app.api.payment.save_payment_result",
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            frappe.db.set_value("Payment Transaction",request_id, {
                "payment_status": "Success",
                "bank_reference": bank_reference,
                "processed_at": now()
            })
            frappe.db.commit()
            
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"ERP Sync Failure - {request_id}")


def handle_pending_failure(transaction, result,request_id):
    failure_reason = result.get("response_message") or "Bank declined payment."

    payload = {
        "invoice_id": transaction.erp_invoice,
        "transaction_id":request_id,
        "amount": transaction.amount,
        "mobile": transaction.mobile,
        "status": "FAILED",
        "bank_reference": result.get("transaction_id"),
        "failure_reason": failure_reason
    }

    print('THIS REQ ID',request_id)

    try:
        requests.post(
            "http://erp.site:8000/api/method/intial_app.api.payment.save_payment_result",
            json=payload,
            timeout=30
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"ERP Sync Failure on Rejection - {request_id}")

    frappe.db.set_value("Payment Transaction", request_id, {
        "payment_status": "Failed",
        "bank_reference": result.get("transaction_id"),
        "failure_reason": failure_reason,
        "processed_at": now()
    })
    frappe.db.commit()
    
@frappe.whitelist(allow_guest=True)
def check_pending_payments():

    print("STARTED SCHEDULAR !!!!")

    pending_transactions = frappe.get_all(
        "Payment Transaction",
        filters={"payment_status": "Pending"},
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

    processed = 0
    failed = 0
    no_response = 0

    for transaction in pending_transactions:
        try:
            result = get_payment_status_from_bank(transaction)
            print(transaction.name)
            print(transaction)
            print(result)
            if not result:
                no_response += 1
                continue

            request_id =  result.request_id

            status = str(
                result.get("payment_status") or ""
            ).upper()

            print(status)

            if status == "COMPLETED":
                handle_pending_success(transaction, result,request_id)
                processed += 1

            elif status in ["FAILED", "REJECTED", "ERROR"]:
                handle_pending_failure(transaction, result,request_id)
                processed += 1

        except Exception:
            failed += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Pending Polling Loop Error - {transaction.name}"
            )

    return {
        "success": True,
        "message": "Pending payment check completed.",
        "total_pending": len(pending_transactions),
        "processed": processed,
        "no_bank_response": no_response,
        "failed": failed
    }

# def remove_pending_otp():
#     pending_otps = frappe.get_all(
#         "OTP Verification",
#         filters={"status": "Pending"},
#         fields=["name"]
#     )

#     # frappe.log_error(
#     # "AUTOMATIC SCHEDULER TEST",
#     #     "Middleware Scheduler"
#     # )

#     for otp in pending_otps:
#         print(otp,"DELETED FROM OTP DOCTYPE VIA HOOKS")
#         frappe.delete_doc("OTP Verification", otp.name)

#     frappe.db.commit()