import streamlit as st

def show_page():
    st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
    
    dashboard_cards = {
        "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير العصرية"},
        "⭐ لوحة المفضلة (1-20)": {"icon": "⭐", "color": "linear-gradient(135deg, #e11d48, #be123c)", "desc": "الأصناف المفضلة للكاشير"},
        "📦 إدارة المخزن والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإدارة وتعديل أسعار الفروع والباركود"},
        "➕ الفائض والتوالف والمرتجعات وتعديل السعر": {"icon": "➕", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "إضافة فائض، توالف، وتعديل السعر وتعميمه"},
        "🔄 تزويد الفروع والأرشيف": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تزويد الفروع وسجل الفواتير السابقة"},
        "🥜 التحميص والخلط": {"icon": "🥜", "color": "linear-gradient(135deg, #d946ef, #a21caf)", "desc": "التحميص وخلط المكسرات وتحديد متوسط التكلفة"}
    }

    def set_page(page_name): 
        st.session_state["page"] = page_name
        st.rerun()

    cols = st.columns(3)
    for i, (item, data) in enumerate(dashboard_cards.items()):
        with cols[i % 3]:
            st.markdown(f'''
            <div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;">
                <h1 style="margin:0; font-size: 45px; color: white !important;">{data['icon']}</h1>
                <h3 style="margin: 10px 0 5px 0; color: white !important;">{item}</h3>
                <p style="margin:0; font-size: 14px; opacity: 0.9; color: white !important;">{data['desc']}</p>
            </div>
            ''', unsafe_allow_html=True)
            
            if st.button(f"دخول ➔", key=f"btn_card_{i}", on_click=set_page, args=(item,)): 
                pass
            st.markdown("<br>", unsafe_allow_html=True)
