import importlib.util
import os
import sys

# دالة تحميل آمنة تفحص وجود الملف، تدعم POS و POS_2، وتتحقق من دالة show_page، وتظهر الخطأ الحقيقي إن فشلت
def load_screen_module(module_name):
    # دعم خاص لـ pos للبحث عن pos.py أو pos_2.py
    possible_files = [f"{module_name}.py"]
    if module_name == "pos":
        possible_files = ["pos.py", "pos_2.py"]
        
    target_file = None
    for f in possible_files:
        full_path = os.path.join(current_dir, f)
        if os.path.exists(full_path):
            target_file = full_path
            break
            
    if not target_file:
        st.error(f"❌ خطأ: ملف الشاشة `{module_name}.py` غير موجود في مسار المشروع.")
        return None
        
    try:
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        
        # التأكد أن الـ Module يحتوي على الدالة الأساسية show_page()
        if not hasattr(mod, "show_page"):
            st.error(f"❌ خطأ برمجي: الملف `{target_file}` لا يحتوي على الدالة الأساسية `show_page()`.")
            return None
            
        return mod
    except Exception as e:
        # إظهار الخطأ الحقيقي والرسالة التفصيلية مباشرة
        st.error(f"❌ فشل استيراد الشاشة `{module_name}` من الملف `{target_file}`.\n\n**تفاصيل الخطأ الحقيقي:** `{e}`")
        return None

# تحميل كافة وحدات الشاشات عبر الدالة الآمنة الجديدة
dashboard = load_screen_module("dashboard")
pos = load_screen_module("pos")
branches = load_screen_module("branches")
users = load_screen_module("users")
adjustments = load_screen_module("adjustments")
items_import = load_screen_module("items_import")
expenses = load_screen_module("expenses")
parties = load_screen_module("parties")
purchases = load_screen_module("purchases")
transfers = load_screen_module("transfers")
favorites = load_screen_module("favorites")
inventory = load_screen_module("inventory")
roasting_blending = load_screen_module("roasting_blending")
reports = load_screen_module("reports")
