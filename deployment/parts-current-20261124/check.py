"""Read-only financial/role checks, with only temporary existing-account sessions."""
import hashlib,json,os,re,sys,time
from datetime import date
from decimal import Decimal
from pathlib import Path
stage=Path(__file__).resolve().parent;phase=sys.argv[1];assert phase in {'before','after'}
assert os.environ.get('COMPUTERNAME')=='BODEFM' and re.fullmatch(r'C:\\Mining360\\control\\parts-current-[0-9a-f]{8}',str(stage))
sys.path.insert(0,r'C:\Mining360\app');os.chdir(r'C:\Mining360\app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
import django;django.setup()
from django.conf import settings
from django.utils import timezone
from django.db import connection
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client
from reports.models import PlatformUser,PartsSalesSynchronizationRun
from reports.access_control import is_platform_admin
from reports.platform_roles import has_business_role
from reports.business_command_center_service import BusinessCommandCenterService
from reports.parts_fulfillment_service import PartsFulfillmentService,MEASURES
import requests
assert connection.vendor=='microsoft' and connection.settings_dict['NAME']=='Mining360App'
with connection.cursor() as c:
 c.execute("SELECT CAST(SERVERPROPERTY('MachineName') AS nvarchar(128))");assert c.fetchone()[0]=='BODEFM'
 c.execute("SELECT COUNT(*) FROM sys.indexes WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='bo_active_revenue_cover_20261010' AND is_disabled=0");assert c.fetchone()[0]==1
 c.execute("SELECT precision,scale FROM sys.columns WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='revenue_eur'");assert tuple(c.fetchone())==(28,10)
if phase=='before':assert not PartsSalesSynchronizationRun.objects.filter(status='Running').exists(),'Wait for the existing Parts import before the runtime switch.'
digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
users=get_user_model()
access=digest([list(PlatformUser.objects.order_by('pk').values('pk','django_user_id','user_principal_name','email','is_active','is_platform_admin','business_performance_role','business_performance_scope','can_access_reporting','can_access_ai','can_access_data','can_access_sources','directory_groups_json')),
 list(users.objects.order_by('pk').values('pk','password','is_active','is_staff','is_superuser')),list(users.groups.through.objects.order_by('pk').values()),list(users.user_permissions.through.objects.order_by('pk').values())])
owner=PlatformUser.objects.select_related('django_user').get(email__iexact='papa.diagne@neemba.com',is_active=True,django_user__is_active=True).django_user
samples=[]
for trial in range(3):
 service=BusinessCommandCenterService(owner,{'period':'ytd','business_line':'parts'});started=time.monotonic();context=service._context();core=service._build_core(*context)
 values={key:core.get(key) for key in ('hero','business_lines','trend','trends','dimensions','sales','leaderboards') if key in core}
 samples.append({'seconds':round(time.monotonic()-started,3),'source_run':str(context[-1].pk),'financial_hash':digest(values)})
service=PartsFulfillmentService(owner);month=timezone.localdate().strftime('%Y-%m')
current=service.summary(month)
assert current['ready'] and not current['empty']
profiles=list(PlatformUser.objects.filter(is_active=True,django_user__is_active=True).select_related('django_user'))
readers=[p for p in profiles if not is_platform_admin(p.django_user) and has_business_role(p.django_user,'business_overview')]
denied=[p for p in profiles if not is_platform_admin(p.django_user) and not has_business_role(p.django_user,'business_overview')]
roles=[]
for profile,role,expected in [(readers[0],'business_reader',200),(denied[0],'other_reader',403)]:
 client=Client();client.force_login(profile.django_user,backend='django.contrib.auth.backends.ModelBackend');session=client.session;session.set_expiry(300);session.save();key=session.session_key
 http=requests.Session();http.trust_env=False;http.cookies.set(settings.SESSION_COOKIE_NAME,key,domain='mining360.neemba.com',path='/',secure=True)
 try:
  view=http.get('https://mining360.neemba.com/business-review/command-center/',timeout=(5,30),allow_redirects=False)
  config=http.get('https://mining360.neemba.com/system-config/',headers={'Accept':'application/json'},timeout=(5,30),allow_redirects=False)
  assert view.status_code==expected and config.status_code==403
  roles.append({'role':role,'http':view.status_code,'config_http':config.status_code})
 finally:http.close();Session.objects.filter(session_key=key).delete()
result={'phase':phase,'access_signature':access,'samples':samples,'roles':roles,'selected_month':current['selected_month'],
 'kpis':current['kpis'],'series':current['series'],'source':current['source'],'temporary_sessions_removed':True,'emails_sent':False}
if phase=='after':
 before=json.loads((stage/'checks-before.json').read_text(encoding='utf-8'))
 assert before['access_signature']==access
 assert {(r['source_run'],r['financial_hash']) for r in before['samples']}=={(r['source_run'],r['financial_hash']) for r in samples}
 assert service.summary()['selected_month']==month
 for old,new in zip(before['series'],current['series']):
  assert old['month']==new['month']
  for key in MEASURES:
   if old[key] is None or new[key] is None:assert old[key]==new[key]
   else:assert abs(Decimal(old[key])-Decimal(new[key]))<=Decimal('.01')
 assert len(before['series'])==len(current['series'])
 assert current['changes']['orders']['basis']=='month_to_date' and current['changes']['sales']['basis']=='month_to_date'
 result['changes']=current['changes'];result['default_current_month']=True
(stage/('checks-'+phase+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
