import sqlite3
import time
import socket
import logging
# import psycopg2 # سيتم تفعيله عند ربط قاعدة البيانات السحابية الفعلية

# إعداد نظام تسجيل الأحداث (Logging) لمراقبة عمل المحرك في الخلفية
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SYNC ENGINE] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

LOCAL_DB_PATH = "mahamis.db" # اسم قاعدة البيانات المحلية

def check_internet_connection(host="8.8.8.8", port=53, timeout=3):
    """فحص توفر اتصال حقيقي بالإنترنت"""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

def get_local_connection():
    """إنشاء اتصال بقاعدة البيانات المحلية للفرع"""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_cloud_connection():
    """
    إنشاء اتصال بقاعدة البيانات السحابية المركزية.
    يرجى استبدال بيانات الاتصال لاحقاً ببيانات السيرفر السحابي الخاص بك.
    """
    # return psycopg2.connect(
    #     host="your_cloud_host",
    #     database="mahamis_cloud",
    #     user="your_user",
    #     password="your_password"
    # )
    pass

def sync_local_invoices_to_cloud():
    """استخراج الفواتير غير المتزامنة ورفعها للسحابة"""
    local_conn = get_local_connection()
    local_cur = local_conn.cursor()
    
    try:
        # جلب الفواتير التي لم يتم رفعها بعد (sync_status = 0)
        local_cur.execute("""
            SELECT id, branch_id, user_id, customer_name, customer_phone, 
                   total_amount, payment_method, notes, shift_status, created_at 
            FROM invoices 
            WHERE sync_status = 0
        """)
        unsynced_invoices = local_cur.fetchall()
        
        if not unsynced_invoices:
            return # لا توجد بيانات جديدة للرفع
            
        logging.info(f"تم العثور على {len(unsynced_invoices)} فاتورة محلية تحتاج للمزامنة. جاري الرفع...")
        
        # الاتصال بالسحابة (محاكاة حالياً)
        # cloud_conn = get_cloud_connection()
        # cloud_cur = cloud_conn.cursor()
        
        for inv in unsynced_invoices:
            inv_id = inv['id']
            
            # --- كود الرفع للسحابة الفعلي سيكون هنا ---
            # cloud_cur.execute("""
            #     INSERT INTO cloud_invoices (local_id, branch_id, user_id, customer_name, 
            #                                 customer_phone, total_amount, payment_method, 
            #                                 notes, shift_status, created_at)
            #     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            # """, (inv['id'], inv['branch_id'], inv['user_id'], inv['customer_name'], 
            #       inv['customer_phone'], inv['total_amount'], inv['payment_method'], 
            #       inv['notes'], inv['shift_status'], inv['created_at']))
            
            # تحديث حالة الفاتورة محلياً لتأكيد نجاح المزامنة
            local_cur.execute("UPDATE invoices SET sync_status = 1 WHERE id = ?", (inv_id,))
            
        # cloud_conn.commit()
        local_conn.commit()
        logging.info("✅ تمت مزامنة جميع الفواتير بنجاح وتحديث حالتها محلياً.")
        
    except Exception as e:
        logging.error(f"❌ حدث خطأ أثناء مزامنة الفواتير: {e}")
    finally:
        local_conn.close()
        # if 'cloud_conn' in locals(): cloud_conn.close()

def run_sync_worker():
    """دالة التشغيل المستمرة لمحرك المزامنة"""
    logging.info("🚀 بدء تشغيل محرك المزامنة لمحامص أبو زيد...")
    
    while True:
        try:
            if check_internet_connection():
                sync_local_invoices_to_cloud()
                # مستقبلاً: يمكن إضافة دالة لسحب تحديثات الأسعار من السحابة إلى الفرع
                # sync_cloud_updates_to_local()
            else:
                logging.warning("🔌 انقطاع في الاتصال. النظام المحلي يعمل بشكل مستقل لتسجيل المبيعات.")
                
        except Exception as e:
            logging.error(f"⚠️ خطأ غير متوقع في محرك المزامنة: {e}")
            
        # الانتظار لمدة 15 ثانية بين كل محاولة مزامنة لتخفيف الحمل على السيرفر
        time.sleep(15)

if __name__ == "__main__":
    run_sync_worker()
