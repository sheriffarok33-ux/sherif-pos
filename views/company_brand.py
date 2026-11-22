"""Customer identity for HTML print templates, read without writing settings."""
from html import escape


def company_label():
    from views.sales_invoice_a4 import _branding_connection, read_branding
    try:
        conn = _branding_connection()
        try:
            brand = read_branding(conn)
        finally:
            conn.close()
    except Exception:
        brand = {}
    return escape(str(brand.get('trade_name') or brand.get('company_name') or 'المنشأة'), quote=True)