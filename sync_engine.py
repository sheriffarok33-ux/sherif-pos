import sqlite3
import time
import socket
# import psycopg2  # سيتم استخدامه لاحقاً للاتصال بقاعدة البيانات السحابية (PostgreSQL)

# 1. دالة للتحقق من وجود اتصال بالإنترنت
def is_connected():
    try:
        # محاولة الاتصال بخادم موثوق (مثل DNS جوجل)
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

# 2. إعداد الاتصال بقواعد البيانات
def get_local_conn():
    # الاتصال بقاعدة البيانات المحلية المستخدمة في فروع المحمصة
    return sqlite3.connect("local_mahamis.db")

def get_cloud_conn():
    # هنا سيتم وضع تفاصيل الاتصال بقاعدة البيانات السحابية المركزية
    # return psycopg2.connect(host="cloud_host", user="user", password="password", dbname="cloud_db")
    pass 

# 3. دالة رفع الفواتير المحلية غير المتزامنة إلى السحابة
def push_local_invoices_to_cloud():
    local_conn = get_local_conn()
    local_cur = local_conn.cursor()
    
    # جلب الفواتير التي لم تتم مزامنتها بعد (sync_status = 0)
    local_cur.execute("SELECT id, branch_id, total_amount, payment_method, notes FROM invoices WHERE sync_status = 0")
    unsynced_invoices = local_cur.fetchall()
    
    if not unsynced_invoices:
        local_conn.close()
        return

    try:
        # cloud_conn = get_cloud_conn()
        # cloud_cur = cloud_conn.cursor()
        
        for inv in unsynced_invoices:
            inv_id = inv[0]
            # محاكاة إدراج الفاتورة في السحابة
            print(f"🔄 جاري رفع الفاتورة رقم {inv_id} إلى السحابة...")
            # cloud_cur.execute("INSERT INTO invoices (...) VALUES (...)", inv)
            
            # بعد نجاح الرفع، يتم تحديث حالة الفاتورة محلياً لتجنب رفعها مجدداً
            local_cur.execute("UPDATE invoices SET sync_status = 1 WHERE id = ?", (inv_id,))
            
        # cloud_conn.commit()
        local_conn.commit()
        print("✅ تمت مزامنة الفواتير بنجاح.")
        
    except Exception as e:
        print(f"⚠️ حدث خطأ أثناء المزامنة: {e}")
    finally:
        local_conn.close()
        # cloud_conn.close()

# 4. محرك العمل المستمر (Background Worker)
def run_sync_engine():
    print("🚀 بدء تشغيل محرك مزامنة محامص أبو زيد...")
    while True:
        if is_connected():
            print("🌐 الإنترنت متصل. جاري بدء المزامنة...")
            push_local_invoices_to_cloud()
            # يمكن إضافة دوال أخرى هنا مثل:
            # pull_new_items_from_cloud() لتحديث الأسعار من الإدارة
        else:
            print("🔌 لا يوجد اتصال بالإنترنت. النظام يعمل محلياً بسلاسة.")
            
        # الانتظار لمدة 30 ثانية قبل الفحص التالي (يمكن تعديل المدة)
        time.sleep(30)

if __name__ == "__main__":
    run_sync_engine()
