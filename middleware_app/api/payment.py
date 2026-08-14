import frappe
import random
import hashlib
import json


def generate_otp():
    return str(
        random.randint(100000, 999999)
    )


def hash_otp(otp):
    return hashlib.sha256(
        str(otp).encode()
    ).hexdigest()


def send_otp_sms(mobile, otp):

    message = (
        f"Your payment OTP is {otp}. "
        "Do not share this OTP with anyone."
    )

    frappe.logger().info(
        f"OTP SMS to {mobile}: {message}"
    )

    return True

@frappe.whitelist(allow_guest=True)
def request_otp(mobile):

    if not mobile:
        frappe.throw("Mobile number is required.")

    otp = generate_otp()
    print(otp)

    otp_hash = hash_otp(otp)

    transaction = frappe.get_doc({
        "doctype": "Payment Transaction",
        "mobile": mobile,
        "payment_status": "Pending"
    })

    transaction.insert(
        ignore_permissions=True
    )
 
    otp_verification = frappe.get_doc({

        "doctype": "OTP Verification",

        "transaction_id":
            transaction.name,

        "mobile":
            mobile,

        "otp_hash":
            otp_hash,

        "attempt_count":
            0,

        "status":
            "Pending",

        "created_at":
            frappe.utils.now()
    })

    otp_verification.insert(
        ignore_permissions=True
    )

    send_otp_sms(
        mobile,
        otp
    )

    return {

        "success": True,

        "transaction_id":
            transaction.name,

        "otp_verification_id":
            otp_verification.name,

        "message":
            "OTP sent successfully."
    }
@frappe.whitelist(allow_guest=True)
def verify_otp(
    transaction_id,
    otp_verification_id,
    otp
):

    if not transaction_id:
        frappe.throw(
            "Transaction ID is required."
        )

    if not otp_verification_id:
        frappe.throw(
            "OTP Verification ID is required."
        )

    if not otp:
        frappe.throw(
            "OTP is required."
        )

    
    try:

        transaction = frappe.get_doc(
            "Payment Transaction",
            transaction_id
        )

    except frappe.DoesNotExistError:

        return {
            "success": False,
            "message":
                "Payment transaction not found."
        }

    
    try:

        verification = frappe.get_doc(
            "OTP Verification",
            otp_verification_id
        )

    except frappe.DoesNotExistError:

        return {
            "success": False,
            "message":
                "OTP verification not found."
        }

     
    if (
        verification.transaction_id
        != transaction_id
    ):

        return {
            "success": False,
            "message":
                "Invalid OTP transaction."
        }

    
    if verification.status == "Verified":

        return {
            "success": False,
            "message":
                "OTP already verified."
        }

    
    if verification.attempt_count >= 3:

        return {
            "success": False,
            "max_attempts": True,
            "message":
                "Maximum 3 OTP attempts exceeded."
        }

   
    entered_hash = hash_otp(otp)

    

    if entered_hash != verification.otp_hash:

        verification.attempt_count = (
            verification.attempt_count + 1
        )

         
        if verification.attempt_count >= 3:

            verification.status = "Failed"

        verification.save(
            ignore_permissions=True
        )

        return {

            "success": False,

            "transaction_id":
                transaction_id,

            "otp_verification_id":
                otp_verification_id,

            "attempt_count":
                verification.attempt_count,

            "max_attempts":
                verification.attempt_count >= 3,

            "message":
                "Invalid OTP."
        }

     
    verification.status = "Verified"

    verification.verified_at = (
        frappe.utils.now()
    )

    verification.save(
        ignore_permissions=True
    )

    return {

        "success": True,

        "transaction_id":
            transaction_id,

        "otp_verification_id":
            otp_verification_id,

        "attempt_count":
            verification.attempt_count,

        "message":
            "OTP verified successfully."
    }

@frappe.whitelist(allow_guest=True)
def process_payment(
    transaction_id,
    amount,
    currency="INR",
    mobile=None
):

    if not transaction_id:
        return {
            "success": False,
            "status": "FAILED",
            "reason":
                "Transaction ID is required."
        }

    if not amount or float(amount) <= 0:
        return {
            "success": False,
            "status": "FAILED",
            "transaction_id":
                transaction_id,
            "reason":
                "Invalid amount."
        }

    bank_reference = (
        "BANK-" +
        str(random.randint(10000, 99999))
    )

    return {

        "success": True,

        "transaction_id":
            transaction_id,

        "bank_reference":
            bank_reference,

        "status":
            "SUCCESS"
    }


# @frappe.whitelist(allow_guest=True)
# def process_payment(
#     transaction_id,
#     amount,
#     invoice_id=None,
#     install_no=None,
#     mobile=None,
#     receiver_bank_account=None,
#     mode_of_payment=None,
#     sender_account=None
# ):

#     # --------------------------------
#     # Validate transaction
#     # --------------------------------

#     if not transaction_id:

#         return {
#             "success": False,
#             "message": "Transaction ID is required."
#         }

#     try:

#         transaction = frappe.get_doc(
#             "Payment Transaction",
#             transaction_id
#         )

#     except frappe.DoesNotExistError:

#         return {
#             "success": False,
#             "transaction_id": transaction_id,
#             "message": "Payment transaction not found."
#         }

#     # --------------------------------
#     # OTP must be verified
#     # --------------------------------

#     if transaction.otp_status != "Verified":

#         return {
#             "success": False,
#             "transaction_id": transaction_id,
#             "message": "OTP verification required."
#         }

#     # --------------------------------
#     # Duplicate protection
#     # --------------------------------

#     if transaction.payment_status == "Success":

#         return {
#             "success": True,
#             "transaction_id": transaction_id,
#             "status": "SUCCESS",
#             "bank_reference":
#                 transaction.bank_reference,
#             "message":
#                 "Transaction already processed."
#         }

#     # --------------------------------
#     # Validate amount
#     # --------------------------------

#     amount = float(amount)

#     if amount <= 0:

#         return {
#             "success": False,
#             "transaction_id": transaction_id,
#             "message":
#                 "Payment amount must be greater than zero."
#         }

#     # --------------------------------
#     # Update transaction
#     # --------------------------------

#     transaction.amount = amount

#     transaction.currency = "INR"

#     transaction.payment_status = "Processing"

#     transaction.save(
#         ignore_permissions=True
#     )

#     # --------------------------------
#     # Send to Dummy Bank
#     # --------------------------------

#     import requests

#     bank_request = {

#         "transaction_id":
#             transaction_id,

#         "amount":
#             amount,

#         "currency":
#             "INR",

#         "mobile":
#             transaction.mobile
#     }

#     try:

#         bank_response = requests.post(

#             "http://dummy_bank_site:8000/api/method/"
#             "dummy_bank_app.api.payment.process_payment",

#             json=bank_request,

#             timeout=30
#         )

#         bank_response.raise_for_status()

#         bank_result = (
#             bank_response.json()
#             .get("message")
#         )

#     except Exception as e:

#         transaction.payment_status = "Failed"

#         transaction.failure_reason = str(e)

#         transaction.processed_at = (
#             frappe.utils.now()
#         )

#         transaction.save(
#             ignore_permissions=True
#         )

#         return {

#             "success": False,

#             "transaction_id":
#                 transaction_id,

#             "status":
#                 "FAILED",

#             "message":
#                 "Unable to communicate with bank.",

#             "reason":
#                 str(e)
#         }

#     # --------------------------------
#     # Update from Bank response
#     # --------------------------------

#     if bank_result.get("success"):

#         transaction.payment_status = "Success"

#         transaction.bank_reference = (
#             bank_result.get(
#                 "bank_reference"
#             )
#         )

#         transaction.processed_at = (
#             frappe.utils.now()
#         )

#         transaction.save(
#             ignore_permissions=True
#         )

#         response = {

#             "success": True,

#             "transaction_id":
#                 transaction_id,

#             "status":
#                 "SUCCESS",

#             "bank_reference":
#                 transaction.bank_reference,

#             "amount":
#                 amount,

#             "message":
#                 "Payment successful."
#         }

#     else:

#         transaction.payment_status = "Failed"

#         transaction.failure_reason = (
#             bank_result.get(
#                 "reason"
#             )
#         )

#         transaction.processed_at = (
#             frappe.utils.now()
#         )

#         transaction.save(
#             ignore_permissions=True
#         )

#         response = {

#             "success": False,

#             "transaction_id":
#                 transaction_id,

#             "status":
#                 "FAILED",

#             "amount":
#                 amount,

#             "reason":
#                 transaction.failure_reason,

#             "message":
#                 "Payment failed."
#         }
