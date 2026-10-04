import streamlit as st
from database import get_db_connection


def back_button(key="global_back_btn"):
    """زر رجوع صغير لا يزاحم عنوان الشاشة."""
    c_back, _ = st.columns([1.15, 8.85])
    with c_back:
        if st.button("⬅️ رجوع", key=key, use_container_width=True):
            hist = st.session_state.get("_nav_history", [])
            if hist:
                target = hist.pop()
                st.session_state["_nav_history"] = hist
                st.session_state["page"] = target
            else:
                st.session_state["page"] = "🏠 الرئيسية واللوحة"
            st.rerun()


def item_alerts(branch_id=None, key="item_alerts"):
    """تنبيهات مضغوطة: Dropdown فقط، والتفاصيل لا تظهر إلا عند طلب المستخدم."""
    role = str(st.session_state.get("role", "")).strip().lower()
    manager = role in {
        "admin", "general_supervisor", "branch_supervisor",
        "مدير", "المدير", "مشرف عام", "مشرف فرع"
    }
    conn = get_db_connection()
    try:
        params = []
        branch_clause = ""
        if branch_id:
            branch_clause = " AND i.branch_id=?"
            params.append(branch_id)

        expiry = conn.execute(f"""
            SELECT i.item_name, i.quantity, b.branch_name,
                   ib.expiry_date, ib.remaining_quantity
            FROM inventory_batches ib
            JOIN items i ON i.id=ib.item_id
            LEFT JOIN branches b ON b.id=i.branch_id
            WHERE COALESCE(ib.remaining_quantity,0)>0
              AND ib.expiry_date IS NOT NULL
              AND date(ib.expiry_date) <= date('now','+30 day')
              {branch_clause}
            ORDER BY date(ib.expiry_date), i.item_name
            LIMIT 30
        """, params).fetchall()

        low = []
        if manager:
            low = conn.execute(f"""
                SELECT i.item_name, i.quantity, b.branch_name
                FROM items i
                LEFT JOIN branches b ON b.id=i.branch_id
                WHERE COALESCE(i.quantity,0)<=5 {branch_clause}
                ORDER BY i.quantity, i.item_name
                LIMIT 30
            """, params).fetchall()

        total = len(expiry) + len(low)
        if not total:
            return

        choice = st.selectbox(
            f"🚨 التنبيهات ({total})",
            ["إخفاء التفاصيل", "عرض تنبيهات الصلاحية"] +
            (["عرض تنبيهات المخزون المنخفض"] if low else []) +
            (["عرض كل التنبيهات"] if low and expiry else []),
            key=f"{key}_dropdown",
            label_visibility="visible",
        )

        show_expiry = choice in ("عرض تنبيهات الصلاحية", "عرض كل التنبيهات")
        show_low = choice in ("عرض تنبيهات المخزون المنخفض", "عرض كل التنبيهات")

        if show_expiry and expiry:
            st.warning("⚠️ منتهي أو قريب الانتهاء")
            rows = [{
                "الصنف": r["item_name"],
                "الفرع/المخزن": r["branch_name"] or "-",
                "الصلاحية": str(r["expiry_date"]),
                "المتبقي": float(r["remaining_quantity"] or 0),
            } for r in expiry]
            st.dataframe(rows, hide_index=True, use_container_width=True)

        if show_low and low:
            st.warning("⚠️ رصيد 5 أو أقل")
            rows = [{
                "الصنف": r["item_name"],
                "الفرع/المخزن": r["branch_name"] or "-",
                "الرصيد": float(r["quantity"] or 0),
            } for r in low]
            st.dataframe(rows, hide_index=True, use_container_width=True)
    except Exception:
        # التنبيه لا يجب أن يعطل شاشة البيع أو أي عملية أساسية.
        return
    finally:
        conn.close()
