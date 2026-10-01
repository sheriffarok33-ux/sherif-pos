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
            "SELECT setting_key, setting_value FROM app_settings"
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
    if st.session_state.get("role") != "Admin":
        st.error("⛔ تخصيص المظهر متاح للمدير فقط.")
        return

    st.title("🎨 تخصيص مظهر النظام")
    st.caption("الإعدادات تُحفظ في قاعدة البيانات وتظهر لجميع مستخدمي النظام.")

    settings = _get_settings()

    if "appearance_section" not in st.session_state:
        st.session_state["appearance_section"] = "colors"

    c1, c2, c3 = st.columns(3)
    if c1.button("🎨 الألوان", use_container_width=True):
        st.session_state["appearance_section"] = "colors"
        st.rerun()
    if c2.button("🔤 الخط", use_container_width=True):
        st.session_state["appearance_section"] = "font"
        st.rerun()
    if c3.button("🖼️ الشعار والخلفية", use_container_width=True):
        st.session_state["appearance_section"] = "images"
        st.rerun()

    st.markdown("---")
    updated = settings.copy()

    if st.session_state["appearance_section"] == "colors":
        a, b = st.columns(2)
        updated["app_bg_color"] = a.color_picker(
            "لون خلفية البرنامج", settings["app_bg_color"]
        )
        updated["text_color"] = b.color_picker(
            "لون النص", settings["text_color"]
        )

        a, b = st.columns(2)
        updated["sidebar_bg_color"] = a.color_picker(
            "لون القائمة الجانبية", settings["sidebar_bg_color"]
        )
        updated["sidebar_button_color"] = b.color_picker(
            "لون أزرار القائمة الجانبية", settings["sidebar_button_color"]
        )

        a, b = st.columns(2)
        updated["button_color"] = a.color_picker(
            "لون الأزرار", settings["button_color"]
        )
        updated["button_hover_color"] = b.color_picker(
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
        size_choice = a.selectbox(
            "حجم الخط",
            list(size_map.keys()),
            index=list(size_map.keys()).index(current_size)
        )
        weight_choice = b.selectbox(
            "سمك الخط",
            list(weight_map.keys()),
            index=list(weight_map.keys()).index(current_weight)
        )

        updated["font_size"] = size_map[size_choice]
        updated["font_weight"] = weight_map[weight_choice]

        st.info("يتم تطبيق حجم وسمك الخط على البرنامج والقوائم والأزرار.")

    else:
        st.subheader("🖼️ شعار النظام")
        if settings.get("logo_data"):
            st.image(settings["logo_data"], width=180)

        logo = st.file_uploader(
            "رفع شعار جديد",
            type=["png", "jpg", "jpeg", "webp"],
            key="appearance_logo"
        )
        if logo is not None:
            updated["logo_data"] = _file_to_data_uri(logo)

        if st.button("🗑️ حذف الشعار", use_container_width=True):
            updated["logo_data"] = ""
            _save_settings(updated)
            st.success("تم حذف الشعار.")
            st.rerun()

        st.markdown("---")
        st.subheader("🌄 خلفية شاشة تسجيل الدخول")
        if settings.get("login_bg_data"):
            st.image(settings["login_bg_data"], use_container_width=True)

        login_bg = st.file_uploader(
            "رفع خلفية تسجيل الدخول",
            type=["png", "jpg", "jpeg", "webp"],
            key="appearance_login_bg"
        )
        if login_bg is not None:
            updated["login_bg_data"] = _file_to_data_uri(login_bg)

        if st.button("🗑️ حذف خلفية تسجيل الدخول", use_container_width=True):
            updated["login_bg_data"] = ""
            _save_settings(updated)
            st.success("تم حذف الخلفية.")
            st.rerun()

    st.markdown("---")
    s1, s2 = st.columns(2)

    if s1.button("💾 حفظ المظهر", type="primary", use_container_width=True):
        _save_settings(updated)
        st.success("✅ تم حفظ إعدادات المظهر.")
        st.rerun()

    if s2.button("♻️ استعادة الشكل الافتراضي", use_container_width=True):
        _save_settings(DEFAULTS)
        st.success("✅ تمت استعادة الإعدادات الافتراضية.")
        st.rerun()
