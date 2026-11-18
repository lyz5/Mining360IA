"""Read-only financial checks and short-lived existing-account access probes."""
import argparse,hashlib,json,os,re,sys,time
from pathlib import Path

def main():
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['before','after']);args=parser.parse_args()
 directory=Path(__file__).resolve().parent
 if os.environ.get('COMPUTERNAME')!='BODEFM' or not re.fullmatch(r'C:\\Mining360\\control\\turnover-totals-[0-9a-f]{8}',str(directory)):
  raise RuntimeError('Unexpected release check location or host.')
 sys.path.insert(0,r'C:\Mining360\app');os.chdir(r'C:\Mining360\app')
 os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
 import django;django.setup()
 from django.conf import settings
 from django.db import connection
 from django.test import Client
 from django.contrib.sessions.models import Session
 from django.contrib.auth import get_user_model
 from reports.models import PlatformUser
 from reports.platform_roles import has_business_role
 from reports.access_control import is_platform_admin
 from reports.business_review_access_service import has_business_review_permission
 from reports.business_command_center_service import BusinessCommandCenterService
 import requests
 if connection.settings_dict['NAME']!='Mining360App':raise RuntimeError('Unexpected application database.')
 with connection.cursor() as cursor:
  cursor.execute("SELECT CAST(SERVERPROPERTY('MachineName') AS nvarchar(128))")
  if cursor.fetchone()[0]!='BODEFM':raise RuntimeError('Unexpected SQL Server machine.')
  cursor.execute("SELECT COUNT(*) FROM sys.indexes WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='bo_active_revenue_cover_20261010' AND is_disabled=0")
  if cursor.fetchone()[0]!=1:raise RuntimeError('Protected Revenue index unavailable.')
  cursor.execute("SELECT precision,scale FROM sys.columns WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='revenue_eur'")
  if tuple(cursor.fetchone())!=(28,10):raise RuntimeError('Protected Revenue precision changed.')
 def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
 users=get_user_model()
 access=digest([list(PlatformUser.objects.order_by('pk').values()),list(users.objects.order_by('pk').values('pk','password','is_active','is_staff','is_superuser')),
                list(users.groups.through.objects.order_by('pk').values()),list(users.user_permissions.through.objects.order_by('pk').values())])
 owner=PlatformUser.objects.select_related('django_user').get(email__iexact='papa.diagne@neemba.com',is_active=True,django_user__is_active=True).django_user
 samples=[]
 for trial in range(3):
  service=BusinessCommandCenterService(owner,{'period':'ytd','business_line':'parts'})
  start=time.monotonic();context=service._context();core=service._build_core(*context)
  values={key:core.get(key) for key in ('hero','business_lines','trend','trends','dimensions','sales','leaderboards') if key in core}
  samples.append({'trial':trial+1,'seconds':round(time.monotonic()-start,3),'source_run':str(context[-1].pk),'financial_hash':digest(values)})
 profiles=list(PlatformUser.objects.filter(is_active=True,django_user__is_active=True).select_related('django_user'))
 readers=[item for item in profiles if not is_platform_admin(item.django_user) and has_business_role(item.django_user,'business_overview')]
 denied=[item for item in profiles if not is_platform_admin(item.django_user) and not has_business_role(item.django_user,'business_overview')]
 results=[]
 def probe(profile,role):
  user=profile.django_user;client=Client();client.force_login(user,backend='django.contrib.auth.backends.ModelBackend')
  session=client.session;session.set_expiry(300);session.save();key=session.session_key
  http=requests.Session();http.trust_env=False
  http.cookies.set(settings.SESSION_COOKIE_NAME,key,domain='mining360.neemba.com',path='/',secure=True)
  try:
   response=http.get('https://mining360.neemba.com/business-review/command-center/',timeout=(5,25),allow_redirects=False)
   config=http.get('https://mining360.neemba.com/system-config/',headers={'Accept':'application/json'},timeout=(5,25),allow_redirects=False)
   result={'role':role,'http':response.status_code,'config_http':config.status_code,'is_platform_admin':False,
           'read_permission':has_business_review_permission(user,'view_business_command_center')}
   if args.phase=='after':
    if response.status_code!=(200 if role=='business_reader' else 403):raise RuntimeError('Existing role access differs from the expected scope.')
    if config.status_code!=403:raise RuntimeError('A non-admin account gained Config access.')
   return result
  finally:
   http.close();Session.objects.filter(session_key=key).delete()
 if readers:results.append(probe(readers[0],'business_reader'))
 if denied:results.append(probe(denied[0],'other_reader'))
 if args.phase=='after' and not readers:raise RuntimeError('No existing non-admin Business Overview account was available for validation.')
 payload={'phase':args.phase,'access_signature':access,'samples':samples,'existing_account_checks':results,
          'protected_index':True,'precision':'numeric(28,10)','temporary_sessions_removed':True,'source_refresh_requested':False,
          'flags':{name:getattr(settings,name) for name in ('ENABLE_BUSINESS_REVIEW','ENABLE_BUSINESS_COMMAND_CENTER','ENABLE_BUSINESS_COMMAND_CENTER_V2','ENABLE_BUSINESS_COMMAND_CENTER_EXPORT')}}
 if args.phase=='after':
  before=json.loads((directory/'checks-before.json').read_text(encoding='utf-8'))
  if access!=before['access_signature']:raise RuntimeError('Existing users, roles or scope records changed.')
  expected={(item['source_run'],item['financial_hash']) for item in before['samples']}
  if {(item['source_run'],item['financial_hash']) for item in samples}!=expected:raise RuntimeError('Source or financial controls changed.')
  if any(value!='Production' for key,value in payload['flags'].items() if not key.endswith('_EXPORT')):raise RuntimeError('Read rollout was not activated.')
 (directory/('checks-'+args.phase+'.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
 print(json.dumps(payload),flush=True)

if __name__=='__main__':
 try:main()
 except Exception as error:
  import traceback
  location=traceback.extract_tb(error.__traceback__)[-1]
  print(json.dumps({'status':'Failed','error_type':type(error).__name__,'location':f'{Path(location.filename).name}:{location.lineno}'}),flush=True)
  raise SystemExit(1) from None
