"""Committed invoice receipts, separate from issued-number counters."""
from views.device_registry import execute

def invoice_receipt_summary(conn,branch_ids):
    ids=sorted(set(int(b) for b in branch_ids))
    if not ids:return []
    import json
    rows=[]
    # Page within each committed branch so a non-financial record can never hide
    # its preceding actual invoice, without loading the full invoice history.
    for branch in ids:
        offset=0
        while True:
            page=execute(conn,"""SELECT i.branch_id,b.branch_name,i.id AS remote_invoice_id,
                i.invoice_number,i.source_device_id,r.offline_uuid,
                COALESCE(r.device_synced_at,i.created_at) AS received_at,
                COALESCE(NULLIF(i.sold_at::text,''),i.created_at::text) AS sold_at,i.notes,
                d.device_number AS registered_device_number
                FROM invoices i LEFT JOIN offline_sync_receipts r ON r.remote_invoice_id=i.id
                JOIN branches b ON b.id=i.branch_id
                LEFT JOIN branch_devices d ON d.device_id=i.source_device_id AND d.branch_id=i.branch_id
                WHERE i.branch_id=?
                ORDER BY COALESCE(r.device_synced_at,i.created_at) DESC,i.id DESC,r.offline_uuid
                LIMIT 100 OFFSET ?""",(branch,offset)).fetchall()
            found=None
            for value in page:
                try:notes=json.loads(value['notes'] or '{}')
                except (ValueError,TypeError):notes={}
                if not isinstance(notes,dict):notes={}
                if not notes.get('_non_financial') and not notes.get('is_simulated') and not notes.get('_administrative_reversal'):found=value;break
            if found is not None:rows.append(found);break
            if len(page)<100:break
            offset+=100
    serials=execute(conn,'''SELECT DISTINCT ON(branch_id) branch_id,invoice_number
        FROM invoices WHERE branch_id=ANY(?) AND invoice_number ~ '^[0-9]{2,10}-[0-9]{6,18}$'
        AND split_part(invoice_number,'-',1)::BIGINT=branch_id
        ORDER BY branch_id,split_part(invoice_number,'-',2)::BIGINT DESC,id DESC''',(ids,)).fetchall()
    high={int(r['branch_id']):r['invoice_number'] for r in serials}
    result=[]
    for row in rows:
        record=dict(row)
        import json
        try:notes=json.loads(record.pop('notes',None) or '{}')
        except (ValueError,TypeError):notes={}
        if not isinstance(notes,dict):notes={}
        if notes.get('_non_financial') or notes.get('is_simulated') or notes.get('_administrative_reversal'):continue
        record['source_device_number']=notes.get('_source_device_number')
        record['received_at']=str(record['received_at'])
        record['sold_at']=str(record['sold_at']) if record.get('sold_at') is not None else None
        record['highest_issued_serial']=high.get(int(record['branch_id']))
        result.append(record)
    return result

def display_receipt_summary(data,branch_ids):
    import streamlit as st
    from datetime import datetime,timezone
    from zoneinfo import ZoneInfo
    if not data.get('invoice_receipts_supported','last_synced_invoices' in data):
        st.info('إيصالات الفواتير غير متاحة من إصدار خدمة السيرفر الحالي؛ لا يمكن استنتاج آخر فاتورة متزامنة منه.')
        return
    def local_time(value):
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo('Africa/Tripoli')).strftime('%Y-%m-%d %H:%M:%S')
    names={int(b['id']):b['branch_name'] for b in data['branches']}
    by_branch={int(r['branch_id']):r for r in data.get('last_synced_invoices',[])}
    rows=[]
    for bid in sorted(branch_ids):
        row=by_branch.get(int(bid))
        rows.append({'الفرع':names[bid],'آخر فاتورة متزامنة':(row.get('invoice_number') or 'فاتورة مؤكدة دون رقم محفوظ') if row else 'لا توجد فواتير متزامنة',
            'تاريخ ووقت الفاتورة':local_time(row['sold_at']) if row and row.get('sold_at') else '—',
            'وقت الحفظ المؤكد بتوقيت ليبيا':local_time(row['received_at']) if row else '—',
            'رقم الجهاز المسجل حاليًا':row.get('source_device_number') or row.get('registered_device_number') or 'غير متوفر' if row else '—',
            'هوية الجهاز المصدر':row.get('source_device_id') or 'غير متوفر' if row else '—',
            'أعلى رقم تسلسلي محفوظ':row.get('highest_issued_serial') or 'لا يوجد بالنمط الموحد' if row else '—'})
    st.subheader('آخر فاتورة وصلت من كل فرع وحُفظت على السيرفر')
    st.caption('المرجع إيصال حفظ الفاتورة الفعلي، وليس رقم الفاتورة القادمة أو نجاح طلب المزامنة. أعلى الرقم التسلسلي بالنمط الموحد قد يختلف عن آخر فاتورة وصلت. رقم الجهاز المعروض تسجيله الحالي إن بقي مرتبطًا بالفرع؛ هوية المصدر الأصلية محفوظة.')
    st.dataframe(rows,hide_index=True,width='stretch')
