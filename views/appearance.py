from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
import base64
import streamlit as st
from database import get_db_connection


DEFAULTS = {
    "app_bg_color": "#f8fafc",
    "sidebar_bg_color": "#0f172a",
    "sidebar_button_color": "#1e293b",
    "button_color": "#0284c7",
    "button_hover_color": "#0369a1",
    "text_color": "#000000",
    "font_size": "17",
    "font_weight": "900",
    "logo_data": "",
    "login_bg_data": "",
    "company_name": "",
    "business_type": "",
    "invoice_qr_image": "",
    "invoice_qr_enabled": "0",
    "trade_name": "",
    "company_phone": "",
    "company_address": "",
    "tax_number": "",
    "commercial_register": "",
    "scale_enabled": "1",
    "scale_prefix": "90",
    "scale_item_start": "2",
    "scale_item_length": "5",
    "scale_value_start": "7",
    "scale_value_length": "5",
    "scale_value_mode": "price",
    "scale_divisor": "100",
}


def _ensure_settings_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _get_settings():
    conn = get_db_connection()
    try:
        _ensure_settings_table(conn)
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM app_settings WHERE setting_key NOT LIKE 'invoice_qr_asset_%'"
        ).fetchall()
        values = DEFAULTS.copy()
        for row in rows:
            values[row["setting_key"]] = row["setting_value"] or ""
        return values
    finally:
        conn.close()


def _save_settings(values):
    conn = get_db_connection()
    try:
        _ensure_settings_table(conn)
        if values.get("invoice_qr_image"):
            from views.invoice_qr_image import asset_key
            image = values["invoice_qr_image"]
            conn.execute("INSERT INTO app_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT (setting_key) DO NOTHING", (asset_key(image), image))
        for key, value in values.items():
            conn.execute("""
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (setting_key)
                DO UPDATE SET
                    setting_value = EXCLUDED.setting_value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, str(value)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _file_to_data_uri(uploaded):
    if uploaded is None:
        return None
    raw = uploaded.getvalue()
    mime = uploaded.type or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"


def show_page():
    back_button(key="back_appearance")

    current_role = st.session_state.get("role", "")
    if current_role not in ("Super_Admin", "Admin", "Manager", "General_Supervisor"):
        st.error("⛔ تخصيص المظهر متاح للإدارة فقط.")
        return

    st.title("🎨 تخصيص مظهر النظام")

    settings = _get_settings()

    if "appearance_section" not in st.session_state:
        st.session_state["appearance_section"] = "colors"

    nav_cols = st.columns(6 if current_role == "Super_Admin" else 4)
    if nav_cols[0].button("🎨 الألوان", use_container_width=True):
        st.session_state["appearance_section"] = "colors"
        st.rerun()
    if nav_cols[1].button("🔤 الخط", use_container_width=True):
        st.session_state["appearance_section"] = "font"
        st.rerun()
    if nav_cols[2].button("🖼️ الشعار والخلفية", use_container_width=True):
        st.session_state["appearance_section"] = "images"
        st.rerun()
    next_idx = 3
    if current_role == "Super_Admin":
        if nav_cols[3].button("🏢 هوية المنشأة والترخيص", use_container_width=True):
            st.session_state["appearance_section"] = "company"
            st.rerun()
        if nav_cols[4].button("🧾 إعدادات الفواتير", use_container_width=True):
            st.session_state["appearance_section"] = "invoice"
            st.rerun()
        next_idx = 5
    elif st.session_state.get("appearance_section") in ("company", "invoice"):
        st.session_state["appearance_section"] = "colors"
    if nav_cols[next_idx].button("⚖️ إعدادات الميزان", use_container_width=True):
        st.session_state["appearance_section"] = "scale"
        st.rerun()

    st.markdown("---")
    updated = settings.copy()

    if st.session_state["appearance_section"] == "colors":
        a, b = st.columns(2)
        updated["app_bg_color"] = ui_field(a.color_picker, "appearance:133", 
            "لون خلفية البرنامج", settings["app_bg_color"]
        )
        updated["text_color"] = ui_field(b.color_picker, "appearance:136", 
            "لون النص", settings["text_color"]
        )

        a, b = st.columns(2)
        updated["sidebar_bg_color"] = ui_field(a.color_picker, "appearance:141", 
            "لون القائمة الجانبية", settings["sidebar_bg_color"]
        )
        updated["sidebar_button_color"] = ui_field(b.color_picker, "appearance:144", 
            "لون أزرار القائمة الجانبية", settings["sidebar_button_color"]
        )

        a, b = st.columns(2)
        updated["button_color"] = ui_field(a.color_picker, "appearance:149", 
            "لون الأزرار", settings["button_color"]
        )
        updated["button_hover_color"] = ui_field(b.color_picker, "appearance:152", 
            "لون الزر عند المرور عليه", settings["button_hover_color"]
        )

    elif st.session_state["appearance_section"] == "font":
        size_map = {
            "عادي": "17",
            "كبير": "19",
            "كبير جداً": "21",
        }
        weight_map = {
            "خفيف": "400",
            "متوسط": "700",
            "عريض": "900",
        }

        current_size = next(
            (k for k, v in size_map.items() if v == settings["font_size"]),
            "عادي"
        )
        current_weight = next(
            (k for k, v in weight_map.items() if v == settings["font_weight"]),
            "عريض"
        )

        a, b = st.columns(2)
        size_choice = ui_field(a.selectbox, "appearance:178", 
            "حجم الخط",
            list(size_map.keys()),
            index=list(size_map.keys()).index(current_size)
        )
        weight_choice = ui_field(b.selectbox, "appearance:183", 
            "سمك الخط",
            list(weight_map.keys()),
            index=list(weight_map.keys()).index(current_weight)
        )

        updated["font_size"] = size_map[size_choice]
        updated["font_weight"] = weight_map[weight_choice]


    elif st.session_state["appearance_section"] == "company" and current_role == "Super_Admin":
        st.subheader("🏢 هوية المنشأة — Super Admin فقط")
        st.caption("هذه البيانات محمية ولا يمكن للـ Admin أو أي فئة تشغيلية تغييرها.")
        a, b = st.columns(2)
        updated["company_name"] = ui_field(a.text_input, "appearance:198", "اسم الشركة / المجموعة", settings.get("company_name", ""))
        updated["trade_name"] = ui_field(b.text_input, "appearance:199", "الاسم التجاري", settings.get("trade_name", ""))
        a, b = st.columns(2)
        updated["company_phone"] = ui_field(a.text_input, "appearance:201", "الهاتف", settings.get("company_phone", ""))
        updated["company_address"] = ui_field(b.text_input, "appearance:202", "العنوان", settings.get("company_address", ""))
        a, b = st.columns(2)
        updated["tax_number"] = ui_field(a.text_input, "appearance:204", "الرقم الضريبي", settings.get("tax_number", ""))
        updated["commercial_register"] = ui_field(b.text_input, "appearance:205", "السجل التجاري", settings.get("commercial_register", ""))
        updated["business_type"] = ui_field(st.text_input, "appearance:business_type", "نوع النشاط التجاري", settings.get("business_type", ""))

    elif st.session_state["appearance_section"] == "invoice" and current_role == "Super_Admin":
        from views.invoice_qr_image import image_data_uri
        st.subheader("🧾 إعدادات الفواتير")
        st.caption("تطبق إعدادات QR على الفواتير الجديدة، وتحتفظ إعادة الطباعة بصورة الفاتورة الأصلية.")
        updated["invoice_qr_enabled"] = "1" if ui_field(st.checkbox, "appearance:invoice_qr_enabled", "إظهار QR Code على الفواتير", value=settings.get("invoice_qr_enabled") == "1") else "0"
        if settings.get("invoice_qr_image"):
            st.image(settings["invoice_qr_image"], width=180, caption="الصورة المحفوظة")
        uploaded = ui_field(st.file_uploader, "appearance:invoice_qr", "رفع صورة QR Code", type=["png", "jpg", "jpeg"], key="appearance_invoice_qr_" + str(st.session_state.get("invoice_qr_upload_version", 0)))
        if uploaded is not None:
            try:
                updated["invoice_qr_image"] = image_data_uri(uploaded.getvalue())
                st.image(updated["invoice_qr_image"], width=180, caption="معاينة الصورة قبل الحفظ")
            except ValueError as exc:
                st.error(str(exc))
                updated["invoice_qr_image"] = settings.get("invoice_qr_image", "")
        if st.button("🗑️ حذف صورة QR", use_container_width=True):
            updated["invoice_qr_image"] = ""
            _save_settings(updated)
            st.session_state["invoice_qr_upload_version"] = st.session_state.get("invoice_qr_upload_version", 0) + 1
            notify_success("تم حذف صورة QR من إعدادات الشركة.")
            st.rerun()

    elif st.session_state["appearance_section"] == "scale":
        st.subheader("⚖️ إعدادات باركود الميزان")
        st.caption("هذه الإعدادات خاصة بالأدمن فقط. اضبطها حسب صيغة الباركود التي يطبعها الميزان.")
        updated["scale_enabled"] = "1" if ui_field(st.checkbox, "appearance:210", "تفعيل قراءة باركود الميزان", value=settings.get("scale_enabled", "0") == "1") else "0"
        a, b = st.columns(2)
        updated["scale_prefix"] = ui_field(a.text_input, "appearance:212", "بداية باركود الميزان (Prefix)", settings.get("scale_prefix", "90"), max_chars=6)
        mode_labels = {"الباركود يحتوي الوزن": "weight", "الباركود يحتوي السعر الإجمالي": "price"}
        current_mode = "الباركود يحتوي السعر الإجمالي" if settings.get("scale_value_mode") == "price" else "الباركود يحتوي الوزن"
        mode_choice = ui_field(b.selectbox, "appearance:215", "القيمة الموجودة داخل الباركود", list(mode_labels), index=list(mode_labels).index(current_mode))
        updated["scale_value_mode"] = mode_labels[mode_choice]
        a, b = st.columns(2)
        updated["scale_item_start"] = str(ui_field(a.number_input, "appearance:218", "موضع بداية كود الصنف (يبدأ من 0)", min_value=0, max_value=20, value=int(settings.get("scale_item_start", "2") or 2), step=1))
        updated["scale_item_length"] = str(ui_field(b.number_input, "appearance:219", "عدد أرقام كود الصنف", min_value=1, max_value=12, value=int(settings.get("scale_item_length", "5") or 5), step=1))
        a, b = st.columns(2)
        updated["scale_value_start"] = str(ui_field(a.number_input, "appearance:221", "موضع بداية الوزن/السعر (يبدأ من 0)", min_value=0, max_value=20, value=int(settings.get("scale_value_start", "7") or 7), step=1))
        updated["scale_value_length"] = str(ui_field(b.number_input, "appearance:222", "عدد أرقام الوزن/السعر", min_value=1, max_value=12, value=int(settings.get("scale_value_length", "5") or 5), step=1))
        updated["scale_divisor"] = str(ui_field(st.number_input, "appearance:223", "معامل القسمة", min_value=1.0, value=float(settings.get("scale_divisor", "100") or 100), step=1.0, help="مثال: 250 جرام مخزنة كـ 00250 ومعامل 1000 = 0.250 كجم"))
        st.info("إعداد باركود الميزان: 90 + كود صنف/PLU من 5 أرقام + السعر الإجمالي من 5 أرقام + رقم تحقق. السعر داخل الباركود يُقسم على 100.")

    else:
        st.subheader("🖼️ شعار النظام")
        if settings.get("logo_data"):
            st.image(settings["logo_data"], width=180)

        logo = ui_field(st.file_uploader, "appearance:231", 
            "رفع شعار جديد",
            type=["png", "jpg", "jpeg", "webp"],
            key="appearance_logo"
        )
        if logo is not None:
            updated["logo_data"] = _file_to_data_uri(logo)

        if st.button("🗑️ حذف الشعار", use_container_width=True):
            updated["logo_data"] = ""
            _save_settings(updated)
            notify_success("تم حذف الشعار.")
            st.rerun()

        st.markdown("---")
        st.subheader("🌄 خلفية شاشة تسجيل الدخول")
        if settings.get("login_bg_data"):
            st.image(settings["login_bg_data"], use_container_width=True)

        login_bg = ui_field(st.file_uploader, "appearance:250", 
            "رفع خلفية تسجيل الدخول",
            type=["png", "jpg", "jpeg", "webp"],
            key="appearance_login_bg"
        )
        if login_bg is not None:
            updated["login_bg_data"] = _file_to_data_uri(login_bg)

        if st.button("🗑️ حذف خلفية تسجيل الدخول", use_container_width=True):
            updated["login_bg_data"] = ""
            _save_settings(updated)
            notify_success("تم حذف الخلفية.")
            st.rerun()

    st.markdown("---")
    s1, s2 = st.columns(2)

    if s1.button("💾 حفظ الإعدادات", type="primary", use_container_width=True):
        _save_settings(updated)
        notify_success("✅ تم حفظ الإعدادات.")
        st.rerun()

    if s2.button("♻️ استعادة الشكل الافتراضي", use_container_width=True):
        defaults = DEFAULTS.copy()
        defaults["invoice_qr_image"] = settings.get("invoice_qr_image", "")
        defaults["invoice_qr_enabled"] = settings.get("invoice_qr_enabled", "0")
        _save_settings(defaults)
        notify_success("✅ تمت استعادة الإعدادات الافتراضية.")
        st.rerun()
