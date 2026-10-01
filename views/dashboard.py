import streamlit as st
from database import get_db_connection


# ============================================================
# الصلاحيات
# ============================================================

def is_allowed(menu_name, role):

    if role in [
        "Admin",
        "General_Supervisor"
    ]:
        return True

    if role == "Cashier":
        return menu_name in [
            "🛒 نقطة البيع (POS)",
            "⭐ لوحة المفضلة (1-20)",
            "🔄 تزويد الفروع والأرشيف"
        ]

    if role == "Branch_Supervisor":
        return menu_name in [
            "🛒 نقطة البيع (POS)",
            "📦 إدارة المخزن والفروع",
            "🔄 تزويد الفروع والأرشيف"
        ]

    if role == "Viewer":
        return menu_name in [
            "📊 التقارير والأرباح"
        ]

    return False


# ============================================================
# الإحصائيات
# ============================================================

def get_dashboard_stats():

    conn = None

    try:

        conn = get_db_connection()

        role = st.session_state.get(
            "role",
            ""
        )

        branch_id = st.session_state.get(
            "branch_id"
        )

        # ----------------------------------------------------
        # Admin / General Supervisor
        # يشاهدان إجماليات النظام بالكامل
        # ----------------------------------------------------

        if role in [
            "Admin",
            "General_Supervisor"
        ]:

            sales = conn.execute(
                """
                SELECT COALESCE(
                    SUM(total_amount),
                    0
                )
                FROM invoices
                """
            ).fetchone()[0]

            branches = conn.execute(
                """
                SELECT COUNT(*)
                FROM branches
                """
            ).fetchone()[0]

            inventory = conn.execute(
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        CASE
                            WHEN COALESCE(avg_cost, 0) > 0
                            THEN avg_cost
                            ELSE COALESCE(buy_price, 0)
                        END
                    ),
                    0
                )
                FROM items
                """
            ).fetchone()[0]

            users = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            ).fetchone()[0]

        # ----------------------------------------------------
        # مستخدم مرتبط بفرع
        # ----------------------------------------------------

        elif branch_id is not None:

            sales = conn.execute(
                """
                SELECT COALESCE(
                    SUM(total_amount),
                    0
                )
                FROM invoices
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

            # المستخدم يرى فرعه فقط
            branches = 1

            inventory = conn.execute(
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        CASE
                            WHEN COALESCE(avg_cost, 0) > 0
                            THEN avg_cost
                            ELSE COALESCE(buy_price, 0)
                        END
                    ),
                    0
                )
                FROM items
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

            users = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

        # ----------------------------------------------------
        # مستخدم غير مربوط بفرع
        # ----------------------------------------------------

        else:

            sales = 0.0
            branches = 0
            inventory = 0.0
            users = 0

        return (
            float(sales or 0),
            int(branches or 0),
            float(inventory or 0),
            int(users or 0)
        )

    except Exception as e:

        st.error(
            "❌ تعذر تحميل إحصائيات لوحة التحكم."
        )

        st.code(str(e))

        return (
            0.0,
            0,
            0.0,
            0
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة
# ============================================================

def show_page():

    st.markdown(
        """
        <h2 style="
            color: #0f172a;
            text-align: right;
        ">
        🌟 مجموعة أبو زيد -
        لوحة التحكم الرئيسية (Dashboard)
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.info(
        "💡 مرحباً بك في إدارة مجموعة أبو زيد. "
        "إليك ملخصاً فورياً لحركة العمل "
        "والأداء المالي."
    )

    # ========================================================
    # الإحصائيات
    # ========================================================

    sales, branches, inventory, users = (
        get_dashboard_stats()
    )

    c1, c2, c3, c4 = st.columns(4)

    box_style = (
        "background-color:#ffffff;"
        "padding:15px;"
        "border-radius:8px;"
        "text-align:center;"
        "border:2px solid #cbd5e1;"
        "box-shadow:0 4px 6px "
        "rgba(0,0,0,0.05);"
    )

    c1.markdown(
        f"""
        <div style='{box_style}'>
            <b style='
                color:#0f172a !important;
                font-size:18px;
            '>
                💰 إجمالي المبيعات
            </b>

            <br><br>

            <span style='
                font-size:22px;
                font-weight:900;
                color:#0284c7 !important;
            '>
                {sales:,.2f} د.ل
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    c2.markdown(
        f"""
        <div style='{box_style}'>
            <b style='
                color:#0f172a !important;
                font-size:18px;
            '>
                🏢 الفروع والمخازن
            </b>

            <br><br>

            <span style='
                font-size:22px;
                font-weight:900;
                color:#0284c7 !important;
            '>
                {branches}
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    c3.markdown(
        f"""
        <div style='{box_style}'>
            <b style='
                color:#0f172a !important;
                font-size:18px;
            '>
                📦 قيمة المخزون
            </b>

            <br><br>

            <span style='
                font-size:22px;
                font-weight:900;
                color:#0284c7 !important;
            '>
                {inventory:,.2f} د.ل
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    c4.markdown(
        f"""
        <div style='{box_style}'>
            <b style='
                color:#0f172a !important;
                font-size:18px;
            '>
                👥 طاقم العمل
            </b>

            <br><br>

            <span style='
                font-size:22px;
                font-weight:900;
                color:#0284c7 !important;
            '>
                {users}
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")

    # ========================================================
    # تصميم أزرار الشاشات
    # ========================================================

    st.markdown(
        """
        <style>

        div[data-testid="column"]
        .stButton > button {

            height: 130px;

            font-size: 22px !important;

            font-weight: 900 !important;

            border-radius: 15px;

            background:
                linear-gradient(
                    135deg,
                    #ffffff,
                    #f8fafc
                ) !important;

            border:
                2px solid #cbd5e1 !important;

            box-shadow:
                0 4px 6px
                rgba(0,0,0,0.05) !important;

            white-space: normal;

            transition:
                all 0.3s ease-in-out;

            width: 100%;
        }

        div[data-testid="column"]
        .stButton > button p,

        div[data-testid="column"]
        .stButton > button div,

        div[data-testid="column"]
        .stButton > button span {

            color:
                #0f172a !important;
        }

        div[data-testid="column"]
        .stButton > button:hover {

            border-color:
                #0284c7 !important;

            background:
                linear-gradient(
                    135deg,
                    #f0f9ff,
                    #e0f2fe
                ) !important;

            transform:
                translateY(-5px);

            box-shadow:
                0 8px 15px
                rgba(
                    2,
                    132,
                    199,
                    0.15
                ) !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    # ========================================================
    # الشاشات والصلاحيات
    # ========================================================

    role = st.session_state.get(
        "role",
        ""
    )

    all_screens = [
        "🛒 نقطة البيع (POS)",
        "🏢 إدارة الفروع",
        "👥 إدارة المستخدمين",
        "⭐ لوحة المفضلة (1-20)",
        "📦 إدارة المخزن والفروع",
        "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
        "🔄 تزويد الفروع والأرشيف",
        "📁 استيراد Excel",
        "💰 المصروفات",
        "👥 جهات التعامل",
        "📥 المشتريات",
        "⚙️ الجرد والتصفير السنوي",
        "🥜 التحميص والخلط",
        "📊 التقارير والأرباح"
    ]

    allowed_screens = [
        screen
        for screen in all_screens
        if is_allowed(
            screen,
            role
        )
    ]

    if not allowed_screens:

        st.info(
            "لا توجد شاشات متاحة "
            "لصلاحيتك حالياً."
        )

        return

    # ========================================================
    # شبكة الشاشات
    # ========================================================

    cols = st.columns(3)

    for i, screen_name in enumerate(
        allowed_screens
    ):

        with cols[i % 3]:

            if st.button(
                screen_name,
                key=f"dash_btn_{i}",
                use_container_width=True
            ):

                st.session_state[
                    "page"
                ] = screen_name

                st.rerun()

            st.markdown(
                "<br>",
                unsafe_allow_html=True
            )
