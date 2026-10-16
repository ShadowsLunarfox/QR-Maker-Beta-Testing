import unittest
from urllib.parse import parse_qs, urlsplit

from qr_maker.content import build_payload
from qr_maker.inspection import check_image
from qr_maker.render import Options, build_design, render_image


class ContentTests(unittest.TestCase):
    def test_text_preserves_unicode_whitespace_and_newlines(self):
        text = "  Hello\n你好，世界\n🙂  "
        design = build_design(Options(content_type="Text", text=text, url="not a URL"))
        self.assertEqual(design.payload, text)
        self.assertTrue(check_image(render_image(design), text).ok)

    def test_wifi_escapes_special_characters_and_omits_open_password(self):
        options = Options(content_type="Wi-Fi", wifi_ssid='A;B:C,D"E\\F', wifi_password='pass;:"\\', wifi_hidden=True)
        self.assertEqual(build_payload(options), 'WIFI:T:WPA;S:A\\;B\\:C\\,D\\"E\\\\F;P:pass\\;\\:\\"\\\\;H:true;;')
        opened = build_payload(Options(content_type="Wi-Fi", wifi_ssid="Guest", wifi_security="nopass", wifi_password="unused"))
        self.assertIn("P:;", opened)
        self.assertNotIn("unused", opened)

    def test_phone_and_email_have_correct_uri_encoding(self):
        self.assertEqual(build_payload(Options(content_type="Phone", phone="+60 (12) 345-6789")), "tel:+60123456789")
        payload = build_payload(Options(content_type="Email", email_to="hello+qr@example.com", email_subject="Hello & 你好?", email_body="A\nB & C"))
        parsed = urlsplit(payload)
        self.assertEqual(parsed.scheme, "mailto")
        self.assertEqual(parsed.path, "hello+qr@example.com")
        self.assertEqual(parse_qs(parsed.query), {"subject": ["Hello & 你好?"], "body": ["A\r\nB & C"]})

    def test_contact_escapes_fields_and_folds_unicode_without_splitting_characters(self):
        payload = build_payload(Options(content_type="Contact", contact_name="张三" * 30,
                                        contact_organization="A;B,C\nD", contact_phone="+60 12 345 6789",
                                        contact_email="a@example.com", contact_address="1 Main St", contact_url="example.com"))
        self.assertTrue(payload.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n"))
        self.assertTrue(payload.endswith("END:VCARD\r\n"))
        for line in payload.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        unfolded = payload.replace("\r\n ", "")
        self.assertIn("FN:" + "张三" * 30, unfolded)
        self.assertIn(r"ORG:A\;B\,C\nD", unfolded)
        self.assertIn("URL:https://example.com", unfolded)

    def test_all_content_types_decode_to_the_exact_payload(self):
        variants = [Options(), Options(content_type="Text", text="Line one\nLine two"),
                    Options(content_type="Wi-Fi", wifi_ssid="工作室", wifi_password="a;b:c,d\\e", wifi_hidden=True),
                    Options(content_type="Contact", contact_name="王小明", contact_phone="+60 12 345 6789", contact_email="user@example.com"),
                    Options(content_type="Phone", phone="+60123456789"),
                    Options(content_type="Email", email_to="user@example.com", email_subject="预约", email_body="Hello\nThanks")]
        for options in variants:
            with self.subTest(kind=options.content_type):
                design = build_design(options)
                self.assertTrue(check_image(render_image(design), design.payload).ok)

    def test_invalid_content_produces_actionable_errors(self):
        variants = [Options(content_type="Text"), Options(content_type="Wi-Fi"),
                    Options(content_type="Wi-Fi", wifi_ssid="Guest"),
                    Options(content_type="Contact"), Options(content_type="Phone", phone="call me"),
                    Options(content_type="Email", email_to="invalid"),
                    Options(content_type="Email", email_to="a@example.com", email_subject="Hi\r\nBcc:other@example.com"),
                    Options(content_type="unknown")]
        for options in variants:
            with self.subTest(options=options), self.assertRaises(ValueError):
                build_design(options)


if __name__ == "__main__":
    unittest.main()
