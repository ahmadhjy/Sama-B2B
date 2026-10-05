"""Presentation filters and exports; financial amounts remain from Accounting."""
import csv
import re
from datetime import date
from io import StringIO
from django.http import HttpResponse

def filter_records(data,kind,params,filters):
    key={'statement':'rows','invoices':'invoices','receipts':'receipts'}.get(kind)
    if not key: return data
    data=dict(data)
    rows=list(data.get(key,[]))
    query=params.get('q','').strip().casefold()[:100]
    dates=filters.cleaned_data if filters.is_valid() else {}
    def matches(row):
        if query and query not in ' '.join(str(row.get(k,'')) for k in ('ref','type','description','destination','number','receipt_no','status','kind')).casefold(): return False
        value=str(row.get('date',''))[:10]
        try: day=date.fromisoformat(value)
        except ValueError: return not (dates.get('date_from') or dates.get('date_to'))
        return not ((dates.get('date_from') and day<dates['date_from']) or (dates.get('date_to') and day>dates['date_to']))
    data[key]=[r for r in rows if matches(r)]
    return data

def export_csv(data,kind):
    columns={
        'statement':('rows',[('date','Date'),('ref','Reference'),('type','Service'),('destination','Destination'),('debit','Debit USD'),('credit','Credit USD'),('running_balance','Balance USD')]),
        'invoices':('invoices',[('number','Invoice'),('date','Date'),('total','Total USD'),('paid','Paid USD'),('remaining','Remaining USD'),('status','Status')]),
        'receipts':('receipts',[('receipt_no','Receipt'),('date','Date'),('kind','Type'),('amount','Amount'),('currency','Currency')])}
    key,fields=columns[kind]
    output=StringIO();writer=csv.writer(output);writer.writerow([label for _,label in fields])
    def cell(value,numeric=False):
        text=str(value if value is not None else '')
        if numeric and re.fullmatch(r'-?\d+(?:\.\d+)?',text): return text
        # Spreadsheet applications must not execute user/provider text as a formula.
        if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')): text="'"+text
        return text
    numeric={'debit','credit','running_balance','total','paid','remaining','amount'}
    for row in data.get(key,[]): writer.writerow([cell(row.get(k,''),k in numeric) for k,_ in fields])
    response=HttpResponse('\ufeff'+output.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="HelloSama-{kind}.csv"'
    return response
