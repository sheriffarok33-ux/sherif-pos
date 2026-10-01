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
# تنبيهات صلاحية دفعات المخزون
# ============================================================

def ensure_expiry_batches_table():
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_batches
            (
                id BIGSERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                quantity NUMERIC DEFAULT 0,
                remaining_quantity NUMERIC DEFAULT 0,
                received_date DATE DEFAULT CURRENT_DATE,
                expiry_date DATE,
                unit_cost NUMERIC DEFAULT 0,
                source_type TEXT DEFAULT 'inventory',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_inventory_batches_expiry
            ON inventory_batches(branch_id, expiry_date)
            """
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_expiry_alerts():
    conn = None
    try:
        conn = get_db_connection()
        role = st.session_state.get("role", "")
        branch_id = st.session_state.get("branch_id")

        where_branch = ""
        params = []

        if role not in ["Admin", "General_Supervisor"]:
            if branch_id is None:
                return []
            where_branch = "AND b.branch_id = ?"
            params.append(branch_id)

        return conn.execute(
            f"""
            SELECT
                b.id,
                i.item_code,
                i.item_name,
                br.branch_name,
                b.remaining_quantity,
                b.expiry_date,
                (b.expiry_date - CURRENT_DATE) AS days_left
            FROM inventory_batches b
            JOIN items i ON i.id = b.item_id
            JOIN branches br ON br.id = b.branch_id
            WHERE b.expiry_date IS NOT NULL
              AND COALESCE(b.remaining_quantity, 0) > 0
              AND b.expiry_date <= CURRENT_DATE + INTERVAL '30 days'
              {where_branch}
            ORDER BY b.expiry_date ASC, i.item_name ASC
            """,
            tuple(params)
        ).fetchall()
    finally:
        if conn:
            conn.close()


def show_expiry_alerts():
    try:
        ensure_expiry_batches_table()
        alerts = get_expiry_alerts()
    except Exception as e:
        st.error("❌ تعذر تحميل تنبيهات تواريخ الصلاحية.")
        st.code(str(e))
        return

    if not alerts:
        st.success("✅ لا توجد دفعات مسجلة منتهية أو ستنتهي خلال 30 يوماً.")
        return

    expired = [r for r in alerts if int(r["days_left"]) < 0]
    seven_days = [r for r in alerts if 0 <= int(r["days_left"]) <= 7]
    thirty_days = [r for r in alerts if 8 <= int(r["days_left"]) <= 30]

    st.markdown("### ⏰ تنبيهات صلاحية المخزون")

    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 منتهي الصلاحية", len(expired))
    c2.metric("🟠 خلال 7 أيام", len(seven_days))
    c3.metric("🟡 خلال 30 يوماً", len(thirty_days))

    if expired:
        st.error(
            f"🚨 يوجد {len(expired)} دفعة منتهية الصلاحية "
            "وبها رصيد متبقٍ."
        )
    if seven_days:
        st.warning(
            f"⚠️ يوجد {len(seven_days)} دفعة ستنتهي خلال 7 أيام."
        )
    if thirty_days:
        st.info(
            f"📅 يوجد {len(thirty_days)} دفعة ستنتهي خلال 30 يوماً."
        )

    with st.expander("عرض تفاصيل تنبيهات الصلاحية", expanded=bool(expired)):
        for row in alerts:
            days = int(row["days_left"])
            if days < 0:
                status = f"🔴 منتهي منذ {abs(days)} يوم"
            elif days == 0:
                status = "🔴 ينتهي اليوم"
            elif days <= 7:
                status = f"🟠 متبقي {days} يوم"
            else:
                status = f"🟡 متبقي {days} يوم"

            st.write(
                f"**{row['item_name']}** — {row['item_code']} | "
                f"{row['branch_name']} | "
                f"الرصيد بالدفعة: {float(row['remaining_quantity'] or 0):,.3f} | "
                f"الانتهاء: {row['expiry_date']} | {status}"
            )


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
    # تنبيهات الصلاحية
    # ========================================================

    show_expiry_alerts()

    st.markdown("---")

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
