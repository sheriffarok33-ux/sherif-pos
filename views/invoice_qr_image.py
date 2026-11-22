"""Helpers for customer-supplied invoice QR images.

The returned data URI can be stored in company settings or an invoice snapshot.
No QR is generated and no image is loaded from an external URL.
"""
import base64
import binascii
import io
import hashlib

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg"}


def image_data_uri(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("يجب اختيار صورة لا يتجاوز حجمها 2 ميغابايت.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            mime = _MIME.get(image.format)
            if not mime or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("اختر صورة PNG أو JPG صالحة بحجم مناسب.")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("تعذر قراءة الصورة. اختر ملف PNG أو JPG صالحًا.") from exc
    return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")


def asset_key(data_uri):
    return 'invoice_qr_asset_' + hashlib.sha256(data_uri.encode('ascii')).hexdigest()


def company_name(conn):
    rows = conn.execute("SELECT setting_key, setting_value FROM app_settings WHERE setting_key IN (?, ?)",
                        ('trade_name', 'company_name')).fetchall()
    settings = {row[0]: row[1] for row in rows}
    return settings.get('trade_name') or settings.get('company_name') or ''


def selected_snapshot(conn):
    rows = conn.execute("SELECT setting_key, setting_value FROM app_settings WHERE setting_key IN (?, ?)",
                        ('invoice_qr_enabled', 'invoice_qr_image')).fetchall()
    settings = {row[0]: row[1] for row in rows}
    image = settings.get('invoice_qr_image') or ''
    if settings.get('invoice_qr_enabled') != '1' or not image:
        return '', ''
    key = asset_key(image)
    stored = conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=?', (key,)).fetchone()
    if not stored or stored[0] != image:
        raise ValueError('تعذر العثور على صورة QR المحفوظة؛ احفظ إعدادات الفاتورة مجددًا.')
    return key, image


def load_snapshot(conn, key):
    if not isinstance(key, str) or len(key) != len('invoice_qr_asset_') + 64 or not key.startswith('invoice_qr_asset_'):
        return ''
    row = conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=?', (key,)).fetchone()
    image = row[0] if row else ''
    return image if image and asset_key(image) == key else ''


def invoice_qr_html(snapshot):
    """Render only the image explicitly captured for this invoice."""
    if not isinstance(snapshot, str) or not snapshot.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        return ""
    try:
        raw = base64.b64decode(snapshot.split(",", 1)[1], validate=True)
        if image_data_uri(raw) != snapshot:
            return ""
    except (ValueError, binascii.Error):
        return ""
    return ('<div style="text-align:center;margin:4mm auto;break-inside:avoid">'
            '<img alt="QR Code" src="' + snapshot + '" '
            'style="display:block;width:32mm;max-width:90%;height:auto;margin:auto;'
            'image-rendering:pixelated"></div>')
