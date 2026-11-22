"""Consistent display-only number formatting for SHERIF views."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def decimal_display(value, digits=2):
    try:
        value = Decimal(str(value if value is not None else 0))
        precision = Decimal(1).scaleb(-int(digits))
        return format(value.quantize(precision, rounding=ROUND_HALF_UP), "f").replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        return "0," + "0" * int(digits) if digits else "0"

def excel_literal_text(writer):
    """Report strings are literal text, never user-supplied spreadsheet formulas.

    Preserve numeric/date cell types and exact text. No prefix or visible formatting
    change is introduced. Called before the existing openpyxl writer is closed.
    """
    for sheet in writer.book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'




def gross_margin_display(unit_cost, sale_price):
    """Display gross margin on selling price, never net profit or markup."""
    try:
        cost, sale = Decimal(str(unit_cost)), Decimal(str(sale_price))
        if not cost.is_finite() or not sale.is_finite() or cost < 0 or sale < 0:
            return 'هامش الربح غير متاح: راجع التكلفة وسعر البيع.'
        profit = sale - cost
        percent = decimal_display(profit * 100 / sale, 2) + '%' if sale > 0 else 'غير معرّف لسعر بيع صفري'
        return 'الربح الإجمالي التقديري للوحدة: ' + decimal_display(profit, 2) + ' د.ل؛ الهامش من سعر البيع: ' + percent + ' (قبل المصروفات).'
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return 'هامش الربح غير متاح: التكلفة أو سعر البيع غير صالح.'
