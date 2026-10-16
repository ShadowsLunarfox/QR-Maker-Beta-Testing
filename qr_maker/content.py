"""Build QR payloads without opening links or contacting any service."""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

CONTENT_TYPES = ("URL", "Text", "Wi-Fi", "Contact", "Phone", "Email")
CONTENT_FIELDS = (
    "content_type", "url", "text", "wifi_ssid", "wifi_password", "wifi_security", "wifi_hidden",
    "contact_name", "contact_phone", "contact_email", "contact_organization", "contact_address", "contact_url",
    "phone", "email_to", "email_subject", "email_body",
)
PRIMARY_FIELDS = {"URL": "url", "Text": "text", "Wi-Fi": "wifi_ssid", "Contact": "contact_name",
                  "Phone": "phone", "Email": "email_to"}


def _email(value):
    value = value.strip()
    if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value):
        raise ValueError("Enter a valid email address.")
    return value


def _phone(value):
    value = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+?[0-9]{3,20}", value):
        raise ValueError("Enter a phone number, including the country code when needed.")
    return value


def _wifi_escape(value):
    return re.sub(r'([\\;,:\"])', r"\\\1", value)


def _vcard_escape(value):
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\n").replace(";", r"\;").replace(",", r"\,")


def _fold_vcard(line):
    lines, current, length = [], "", 0
    for character in line:
        size = len(character.encode("utf-8"))
        if length + size > 75:
            lines.append(current)
            current, length = " ", 1
        current += character
        length += size
    return "\r\n".join([*lines, current])


def build_payload(options):
    from .render import normalize_url

    kind = options.content_type
    if kind == "URL":
        return normalize_url(options.url)
    if kind == "Text":
        if not options.text.strip():
            raise ValueError("Enter some text to create your QR code.")
        return options.text
    if kind == "Wi-Fi":
        if not options.wifi_ssid:
            raise ValueError("Enter the Wi-Fi network name (SSID).")
        if options.wifi_security not in ("WPA", "WEP", "nopass"):
            raise ValueError("Choose WPA, WEP, or an open Wi-Fi network.")
        if options.wifi_security != "nopass" and not options.wifi_password:
            raise ValueError("Enter the Wi-Fi password, or choose an open network.")
        password = "" if options.wifi_security == "nopass" else _wifi_escape(options.wifi_password)
        return (f"WIFI:T:{options.wifi_security};S:{_wifi_escape(options.wifi_ssid)};P:{password};"
                f"H:{str(options.wifi_hidden).lower()};;")
    if kind == "Phone":
        return "tel:" + _phone(options.phone)
    if kind == "Email":
        address = _email(options.email_to)
        if "\n" in options.email_subject or "\r" in options.email_subject:
            raise ValueError("Keep the email subject on a single line.")
        parameters = {}
        if options.email_subject:
            parameters["subject"] = options.email_subject
        if options.email_body:
            parameters["body"] = options.email_body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        query = "?" + urlencode(parameters, quote_via=quote) if parameters else ""
        return "mailto:" + quote(address, safe="@.+") + query
    if kind == "Contact":
        name = options.contact_name.strip()
        if not name:
            raise ValueError("Enter the contact's name.")
        lines = ["BEGIN:VCARD", "VERSION:3.0", "FN:" + _vcard_escape(name), "N:;" + _vcard_escape(name) + ";;;"]
        if options.contact_phone.strip():
            lines.append("TEL;TYPE=CELL:" + _phone(options.contact_phone))
        if options.contact_email.strip():
            lines.append("EMAIL:" + _vcard_escape(_email(options.contact_email)))
        if options.contact_organization:
            lines.append("ORG:" + _vcard_escape(options.contact_organization))
        if options.contact_address:
            lines.append("ADR:;;" + _vcard_escape(options.contact_address) + ";;;;")
        if options.contact_url.strip():
            lines.append("URL:" + _vcard_escape(normalize_url(options.contact_url)))
        lines.append("END:VCARD")
        return "\r\n".join(_fold_vcard(line) for line in lines) + "\r\n"
    raise ValueError("Choose a supported QR content type.")


def content_description(options):
    if options.content_type == "URL":
        return "Website link"
    if options.content_type == "Wi-Fi":
        return "Wi-Fi network: " + options.wifi_ssid
    if options.content_type == "Contact":
        return "Contact: " + options.contact_name
    return {"Text": "Plain text", "Phone": "Phone number", "Email": "Email message"}.get(options.content_type, "QR code")
