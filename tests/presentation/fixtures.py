"""Explicit local browser-test data. Never import from application code."""
from copy import deepcopy
from calendar import monthrange


def parts_summary(month=''):
    month=month or '2026-10'
    kpis={'orders':94157590.12,'sales':20100153.90,'current':8416346.36,
          'last':4817567.64,'older':6047941.69,'unallocated':818298.21,'future':0,
          'reconciliation':{'status':'reconciled','label':'Reconciled','difference':0,'arithmetic_difference':0}}
    if month=='2026-09':
        # Signed credit and a future-order control, kept separate from main cohorts.
        kpis.update(current=-100, last=200, older=100,unallocated=50,future=25,sales=275,orders=1000)
    data={'ready':True,'empty':month=='2026-08','message':'No data in this test month',
          'months':['2026-08','2026-09','2026-10'],'selected_month':month,'month_to_date':False,
          'kpis':kpis,'source':{'coverage':'2026-10-31','last_refresh':None,
          'model':'LOCAL UI TEST FIXTURE','scope':'Test scope only','scope_note':'Not a production source.'},
          'changes':{'orders':{'percent':None,'reason':'Comparison unavailable in this UI test fixture'},
                     'sales':{'percent':None,'reason':'Comparison unavailable in this UI test fixture'}},
          'series':[]}
    for value in ['2026-09', '2026-10']:
        row=deepcopy(kpis);row.pop('reconciliation');row['month']=value;data['series'].append(row)
    return data


def parts_details(params):
    cohort=params.get('cohort','')
    labels={'current':'Current Month','last':'Last Month','older':'2+ Months','unallocated':'Unallocated','future':'Future Order'}
    month=params.get('month') or '2026-10'
    year,number=map(int,month.split('-'))
    def shifted(offset):
        value=year*12+number-1+offset
        return f'{value//12:04d}-{value%12+1:02d}-01'
    dates={'current':shifted(0),'last':shifted(-1),'older':shifted(-2),'unallocated':None,'future':shifted(1)}
    kpis=parts_summary(month)['kpis']
    total=kpis[cohort] if cohort else kpis['sales']
    rows=[{'accounting_date':f'{month}-{monthrange(year,number)[1]:02d}',
           'order_date':dates[key], 'order_key':None if key=='unallocated' else f'{123+index:07d}|TEST|01',
           'invoice_key':f'TEST|TEST-01|{index+1:06d}','cohort':labels[key],'amount':kpis[key]}
          for index,key in enumerate(labels) if (not cohort or key==cohort) and kpis[key]!=0]
    return {'ready':True,'pages':1,'page':1,'rows':rows,'total':total,'total_rows':len(rows),
            'search':params.get('search',''),'reconciliation':'reconciled','control_total':total}
