import streamlit as st
from datetime import date, timedelta
from database import get_db_connection

def back_button(key="global_back_btn"):
    if st.button("⬅️ رجوع", key=key):
        hist = st.session_state.get("_nav_history", [])
        if hist:
            target = hist.pop()
            st.session_state["_nav_history"] = hist
            st.session_state["page"] = target
        else:
            st.session_state["page"] = "dashboard"
        st.rerun()

def item_alerts(branch_id=None, key="item_alerts"):
    role = str(st.session_state.get("role","")).strip().lower()
    manager = role in {"admin","general_supervisor","branch_supervisor","مدير","المدير","مشرف عام","مشرف فرع"}
    conn=get_db_connection()
    try:
        params=[]
        branch_clause=""
        if branch_id:
            branch_clause=" AND i.branch_id=?"
            params.append(branch_id)
        expiry=conn.execute(f"""
            SELECT i.item_name, i.quantity, b.branch_name, ib.expiry_date, ib.remaining_quantity
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
        low=[]
        if manager:
            low=conn.execute(f"""
                SELECT i.item_name,i.quantity,b.branch_name
                FROM items i LEFT JOIN branches b ON b.id=i.branch_id
                WHERE COALESCE(i.quantity,0)<=5 {branch_clause}
                ORDER BY i.quantity,i.item_name LIMIT 30
            """, params).fetchall()
        if expiry or low:
            with st.expander("🚨 تنبيهات الأصناف والمخزون", expanded=True):
                if expiry:
                    st.warning("أصناف منتهية أو قاربت صلاحيتها على الانتهاء:")
                    for r in expiry:
                        st.write(f"• {r['item_name']} — {r['branch_name'] or '-'} — الصلاحية: {r['expiry_date']} — المتبقي: {float(r['remaining_quantity'] or 0):,.2f}")
                if low:
                    st.warning("أصناف وصل رصيدها إلى 5 أو أقل:")
                    for r in low:
                        st.write(f"• {r['item_name']} — {r['branch_name'] or '-'} — الرصيد: {float(r['quantity'] or 0):,.2f}")
    except Exception:
        pass
    finally:
        conn.close()
