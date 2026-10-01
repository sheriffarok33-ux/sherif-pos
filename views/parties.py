import streamlit as st
import pandas as pd
from database import get_db_connection


# ============================================================
# تحميل الموردين
# ============================================================

def get_suppliers():

    conn = None

    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                supplier_name,
                phone,
                balance
            FROM suppliers
            ORDER BY supplier_name ASC
            """
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# تحميل الزبائن
# ============================================================

def get_customers():

    conn = None

    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                customer_name,
                phone,
                total_purchases,
                balance,
                created_at
            FROM customers
            ORDER BY total_purchases DESC,
                     customer_name ASC
            """
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# إضافة جهة تعامل
# ============================================================

def add_party(
    party_type,
    name,
    phone
):

    conn = None

    try:

        name = name.strip()
        phone = phone.strip()

        if not name:
            raise ValueError(
                "يجب إدخال اسم الجهة."
            )

        if not phone:
            raise ValueError(
                "يجب إدخال رقم الهاتف."
            )

        conn = get_db_connection()

        # ====================================================
        # مورد
        # ====================================================

        if "مورد" in party_type:

            duplicate = conn.execute(
                """
                SELECT id
                FROM suppliers
                WHERE supplier_name = ?
                   OR phone = ?
                LIMIT 1
                """,
                (
                    name,
                    phone
                )
            ).fetchone()

            if duplicate:
                raise ValueError(
                    "اسم المورد أو رقم الهاتف "
                    "مسجل مسبقاً."
                )

            conn.execute(
                """
                INSERT INTO suppliers
                (
                    supplier_name,
                    phone,
                    balance
                )
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    phone,
                    0.0
                )
            )

            success_message = (
                f"✅ تمت إضافة المورد "
                f"({name}) بنجاح."
            )

        # ====================================================
        # زبون آجل
        # ====================================================

        else:

            duplicate = conn.execute(
                """
                SELECT id
                FROM customers
                WHERE customer_name = ?
                   OR phone = ?
                LIMIT 1
                """,
                (
                    name,
                    phone
                )
            ).fetchone()

            if duplicate:
                raise ValueError(
                    "اسم الزبون أو رقم الهاتف "
                    "مسجل مسبقاً."
                )

            conn.execute(
                """
                INSERT INTO customers
                (
                    customer_name,
                    phone,
                    total_purchases,
                    balance
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    phone,
                    0.0,
                    0.0
                )
            )

            success_message = (
                f"✅ تم اعتماد الزبون الآجل "
                f"({name}) بنجاح."
            )

        conn.commit()

        st.success(
            success_message
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة جهة التعامل."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# سداد مورد
# ============================================================

def pay_supplier(
    supplier_id,
    amount
):

    conn = None

    try:

        if amount <= 0:
            raise ValueError(
                "يجب إدخال مبلغ صحيح."
            )

        conn = get_db_connection()

        supplier = conn.execute(
            """
            SELECT
                id,
                supplier_name,
                balance
            FROM suppliers
            WHERE id = ?
            FOR UPDATE
            """,
            (supplier_id,)
        ).fetchone()

        if not supplier:
            raise ValueError(
                "المورد غير موجود."
            )

        current_balance = float(
            supplier["balance"] or 0
        )

        if current_balance <= 0:
            raise ValueError(
                "لا يوجد رصيد مستحق "
                "لهذا المورد."
            )

        if amount > current_balance:
            raise ValueError(
                f"المبلغ المدفوع "
                f"({amount:,.2f} د.ل) "
                f"أكبر من الرصيد المستحق "
                f"({current_balance:,.2f} د.ل)."
            )

        new_balance = (
            current_balance
            - float(amount)
        )

        conn.execute(
            """
            UPDATE suppliers
            SET balance = ?
            WHERE id = ?
            """,
            (
                new_balance,
                supplier_id
            )
        )

        conn.commit()

        st.success(
            f"✅ تم تسجيل دفعة "
            f"{amount:,.2f} د.ل للمورد "
            f"({supplier['supplier_name']}). "
            f"الرصيد المتبقي: "
            f"{new_balance:,.2f} د.ل."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل دفعة المورد."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تحصيل من زبون
# ============================================================

def collect_customer_payment(
    customer_id,
    amount
):

    conn = None

    try:

        if amount <= 0:
            raise ValueError(
                "يجب إدخال مبلغ صحيح."
            )

        conn = get_db_connection()

        customer = conn.execute(
            """
            SELECT
                id,
                customer_name,
                balance
            FROM customers
            WHERE id = ?
            FOR UPDATE
            """,
            (customer_id,)
        ).fetchone()

        if not customer:
            raise ValueError(
                "الزبون غير موجود."
            )

        current_balance = float(
            customer["balance"] or 0
        )

        if current_balance <= 0:
            raise ValueError(
                "لا توجد مديونية مستحقة "
                "على هذا الزبون."
            )

        if amount > current_balance:
            raise ValueError(
                f"المبلغ المحصل "
                f"({amount:,.2f} د.ل) "
                f"أكبر من المديونية الحالية "
                f"({current_balance:,.2f} د.ل)."
            )

        new_balance = (
            current_balance
            - float(amount)
        )

        conn.execute(
            """
            UPDATE customers
            SET balance = ?
            WHERE id = ?
            """,
            (
                new_balance,
                customer_id
            )
        )

        conn.commit()

        st.success(
            f"✅ تم تحصيل "
            f"{amount:,.2f} د.ل من "
            f"({customer['customer_name']}). "
            f"الرصيد المتبقي: "
            f"{new_balance:,.2f} د.ل."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل تحصيل الزبون."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة
# ============================================================

def show_page():

    st.header(
        "👥 جهات التعامل المعتمدة "
        "(الموردين والزبائن الآجلين)"
    )

    st.info(
        "💡 إدارة الموردين وديون المشتريات، "
        "والزبائن المعتمدين للبيع الآجل "
        "والتحصيل في مكان واحد."
    )

    # ========================================================
    # إضافة جهة
    # ========================================================

    st.markdown(
        "### ➕ إضافة جهة تعامل جديدة "
        "(مورد أو زبون آجل)"
    )

    with st.form(
        "unified_party_form",
        clear_on_submit=True
    ):

        col_u1, col_u2, col_u3 = (
            st.columns(3)
        )

        party_type = col_u1.selectbox(
            "اختر نوع جهة التعامل:",
            [
                "🚛 مورد (تاجر جملة)",
                "🤝 زبون آجل "
                "(مسموح له بالدين)"
            ]
        )

        p_name = col_u2.text_input(
            "اسم الجهة / الشخص:"
        )

        p_phone = col_u3.text_input(
            "رقم الهاتف:"
        )

        add_submit = (
            st.form_submit_button(
                "💾 حفظ واعتماد جهة التعامل",
                type="primary"
            )
        )

    if add_submit:

        add_party(
            party_type,
            p_name,
            p_phone
        )

    st.markdown("---")

    # ========================================================
    # التبويبات
    # ========================================================

    tab_sup, tab_cust = st.tabs(
        [
            "🚛 جدول الموردين والديون",
            "🤝 جدول الزبائن الآجلين والتحصيل"
        ]
    )

    # ========================================================
    # الموردون
    # ========================================================

    with tab_sup:

        st.markdown(
            "### 📋 كشف حساب الموردين "
            "والديون المستحقة"
        )

        try:

            suppliers = get_suppliers()

        except Exception as e:

            st.error(
                "❌ تعذر تحميل الموردين."
            )

            st.code(str(e))

            suppliers = []

        if suppliers:

            supp_df = pd.DataFrame(
                [
                    {
                        "رقم المورد":
                            s["id"],

                        "اسم المورد":
                            s["supplier_name"],

                        "الهاتف":
                            s["phone"],

                        "الرصيد المستحق (د.ل)":
                            float(
                                s["balance"] or 0
                            )
                    }

                    for s in suppliers
                ]
            )

            st.dataframe(
                supp_df,
                use_container_width=True,
                hide_index=True
            )

            total_supplier_debt = sum(
                max(
                    float(
                        s["balance"] or 0
                    ),
                    0
                )
                for s in suppliers
            )

            st.metric(
                "إجمالي المستحق للموردين",
                f"{total_supplier_debt:,.2f} د.ل"
            )

            st.markdown("---")

            st.markdown(
                "**💰 سداد دفعة لمورد "
                "(إرسال نقدية):**"
            )

            sup_list = {
                (
                    f"{s['supplier_name']} "
                    f"(الرصيد: "
                    f"{float(s['balance'] or 0):,.2f} د.ل)"
                ): s

                for s in suppliers
            }

            col_pay1, col_pay2 = (
                st.columns(2)
            )

            sel_pay_sup = col_pay1.selectbox(
                "اختر المورد للسداد:",
                list(sup_list.keys()),
                key="sel_sup_pay_box"
            )

            selected_supplier = (
                sup_list[
                    sel_pay_sup
                ]
            )

            pay_amount = (
                col_pay2.number_input(
                    "المبلغ المدفوع له (د.ل):",
                    min_value=0.0,
                    step=10.0,
                    format="%.2f",
                    key="sup_pay_val_input"
                )
            )

            if st.button(
                "✅ تسجيل الدفعة "
                "وخصمها من حساب المورد",
                key="btn_execute_sup_pay",
                type="primary"
            ):

                pay_supplier(
                    selected_supplier["id"],
                    pay_amount
                )

        else:

            st.info(
                "لا يوجد موردون مسجلون."
            )

    # ========================================================
    # الزبائن
    # ========================================================

    with tab_cust:

        st.markdown(
            "### 📊 قائمة الزبائن المعتمدين "
            "والديون المستحقة"
        )

        try:

            customers = get_customers()

        except Exception as e:

            st.error(
                "❌ تعذر تحميل الزبائن."
            )

            st.code(str(e))

            customers = []

        if customers:

            cust_df = pd.DataFrame(
                [
                    {
                        "رقم الزبون":
                            c["id"],

                        "اسم الزبون":
                            c["customer_name"],

                        "الهاتف":
                            c["phone"],

                        "إجمالي المشتريات (د.ل)":
                            float(
                                c[
                                    "total_purchases"
                                ] or 0
                            ),

                        "الرصيد الآجل المستحق (د.ل)":
                            float(
                                c["balance"] or 0
                            ),

                        "تاريخ التسجيل":
                            c["created_at"]
                    }

                    for c in customers
                ]
            )

            st.dataframe(
                cust_df,
                use_container_width=True,
                hide_index=True
            )

            total_customer_debt = sum(
                max(
                    float(
                        c["balance"] or 0
                    ),
                    0
                )
                for c in customers
            )

            st.metric(
                "إجمالي مديونية الزبائن",
                f"{total_customer_debt:,.2f} د.ل"
            )

            st.markdown("---")

            st.markdown(
                "**💵 تحصيل دفعة من زبون آجل "
                "(قبض نقدية):**"
            )

            cust_list = {
                (
                    f"{c['customer_name']} "
                    f"({c['phone'] or '-'}) "
                    f"- المديونية: "
                    f"{float(c['balance'] or 0):,.2f} د.ل"
                ): c

                for c in customers
            }

            col_cp1, col_cp2 = (
                st.columns(2)
            )

            sel_pay_cust = (
                col_cp1.selectbox(
                    "اختر الزبون للتحصيل منه:",
                    list(
                        cust_list.keys()
                    ),
                    key="sel_cust_pay_box"
                )
            )

            selected_customer = (
                cust_list[
                    sel_pay_cust
                ]
            )

            cust_pay_amount = (
                col_cp2.number_input(
                    "المبلغ المحصل "
                    "والمقبوض (د.ل):",
                    min_value=0.0,
                    step=10.0,
                    format="%.2f",
                    key="cust_pay_val_input"
                )
            )

            if st.button(
                "✅ تسجيل القبض "
                "وخصمه من مديونية الزبون",
                key="btn_execute_cust_pay",
                type="primary"
            ):

                collect_customer_payment(
                    selected_customer["id"],
                    cust_pay_amount
                )

        else:

            st.info(
                "لا يوجد زبائن آجلون "
                "مسجلون حالياً."
            )
