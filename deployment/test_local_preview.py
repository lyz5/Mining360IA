"""Safety boundaries specific to the local preview launcher."""
import io
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from .local_preview import install_network_guards, LocalPreviewApplication, LocalPreviewBanner


class LocalPreviewTests(SimpleTestCase):
    def test_socket_and_native_sql_guards_reject_remote_targets(self):
        import pyodbc
        with patch.object(socket.socket, 'connect') as connect, patch.object(socket.socket, 'connect_ex'), patch.object(pyodbc, 'connect') as odbc, patch('requests.sessions.Session.send'):
            install_network_guards('Mining360App_BODEFM_Local_20261116')
            with socket.socket() as sock:
                sock.connect(('127.0.0.1', 1234))
                connect.assert_called_once()
                for target in ('172.17.0.111', 'BODEFM', 'example.invalid'):
                    with self.assertRaises(OSError): sock.connect((target, 443))
            for value in ('SERVER=BODEFM;DATABASE=Mining360App', 'SERVER=localhost\\MSSQL_IA;DATABASE=MiningProd'):
                with self.assertRaises(RuntimeError): pyodbc.connect(value)
            pyodbc.connect('SERVER=localhost\\MSSQL_IA;DATABASE=Mining360App_BODEFM_Local_20261116;Trusted_Connection=yes')
            odbc.assert_called_once()

    def test_local_mailbox_escapes_content_and_is_loopback_only(self):
        with TemporaryDirectory() as folder:
            state = Path(folder); (state/'mailbox').mkdir()
            (state/'mailbox'/'test.log').write_text('<script>alert(1)</script>', encoding='utf-8')
            wrapped = Mock(); app = LocalPreviewApplication(wrapped, state); response = Mock()
            body=b''.join(app({'PATH_INFO':'/__local__/mailbox/', 'HTTP_HOST':'localhost:8016','REMOTE_ADDR':'127.0.0.1'},response))
            self.assertIn(b'&lt;script&gt;',body);self.assertIn(b'No real email',body)
            self.assertIn(('Cache-Control','private, no-store'),response.call_args.args[1])
            body=b''.join(app({'HTTP_HOST':'evil.invalid','REMOTE_ADDR':'127.0.0.1'},response))
            self.assertEqual(response.call_args.args[0],'403 Forbidden');wrapped.assert_not_called()

    def test_banner_marks_only_html_without_modifying_amounts(self):
        response=HttpResponse('<html><body><strong>20 100 153,90 EUR</strong></body></html>')
        result=LocalPreviewBanner(lambda _:response)(None)
        self.assertIn(b'LOCAL TEST',result.content);self.assertIn(b'20 100 153,90 EUR',result.content)
        self.assertEqual(int(result['Content-Length']),len(result.content))
        response=HttpResponse('{"amount":20100153.90}',content_type='application/json')
        self.assertEqual(LocalPreviewBanner(lambda _:response)(None).content,b'{"amount":20100153.90}')

    @override_settings(LOCAL_PREVIEW_REAL_EMAIL=True)
    def test_real_delivery_never_exposes_the_old_local_mailbox(self):
        with TemporaryDirectory() as folder:
            state=Path(folder);(state/'mailbox').mkdir()
            (state/'mailbox'/'old.log').write_text('OLD-CAPTURED-CODE',encoding='utf-8')
            response=Mock();app=LocalPreviewApplication(Mock(),state)
            body=b''.join(app({'PATH_INFO':'/__local__/mailbox/','HTTP_HOST':'localhost:8016','REMOTE_ADDR':'127.0.0.1'},response))
            self.assertIn(b'Real email delivery is enabled',body)
            self.assertNotIn(b'OLD-CAPTURED-CODE',body)
            result=LocalPreviewBanner(lambda _:HttpResponse('<body>Login</body>'))(None)
            self.assertIn(b'Real email delivery',result.content)
            self.assertNotIn(b'Local mailbox',result.content)


class EmailEgressPolicyTests(SimpleTestCase):
    url='https://mail-test.logic.azure.com/workflows/sign-in/invoke?sig=fixture-only'

    def test_only_the_pinned_flow_can_open_a_remote_socket_during_its_request(self):
        import requests
        from .local_mail_policy import EmailEgressPolicy
        policy=EmailEgressPolicy();policy.allow_email_flow(self.url)
        prepared=requests.Request('POST',self.url).prepare()
        def send(session,request,**kwargs):
            self.assertTrue(policy.socket_allowed(('203.0.113.40',443)))
            self.assertFalse(policy.socket_allowed(('203.0.113.40',80)))
            self.assertFalse(policy.socket_allowed(('172.17.0.111',443)))
            return 'delivered'
        dns=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('203.0.113.40',443))]
        with patch('socket.getaddrinfo',return_value=dns):
            self.assertEqual(policy.send(send,requests.Session(),prepared,allow_redirects=False,verify=True),'delivered')
        self.assertFalse(policy.socket_allowed(('203.0.113.40',443)))

    def test_other_flows_redirects_get_and_disabled_tls_stay_blocked(self):
        import requests
        from .local_mail_policy import EmailEgressPolicy
        policy=EmailEgressPolicy();policy.allow_email_flow(self.url);send=Mock()
        for method,url,options in (
            ('POST',self.url+'&extra=1',{}),('GET',self.url,{}),
            ('POST',self.url,{'allow_redirects':True}),('POST',self.url,{'verify':False}),
            ('POST','https://graph.microsoft.com/v1.0/me',{}),
        ):
            args={'allow_redirects':False,'verify':True,**options}
            with self.assertRaises(OSError):policy.send(send,requests.Session(),requests.Request(method,url).prepare(),**args)
        send.assert_not_called()
        for url in ('http://mail-test.logic.azure.com/invoke','https://untrusted.invalid/invoke'):
            with self.assertRaises(ValueError):policy.allow_email_flow(url)

    def test_failed_send_also_clears_remote_socket_permission(self):
        import requests
        from .local_mail_policy import EmailEgressPolicy
        policy=EmailEgressPolicy();policy.allow_email_flow(self.url)
        dns=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('203.0.113.40',443))]
        with patch('socket.getaddrinfo',return_value=dns):
            with self.assertRaises(RuntimeError):
                policy.send(Mock(side_effect=RuntimeError('not delivered')),requests.Session(),requests.Request('POST',self.url).prepare(),allow_redirects=False)
        self.assertFalse(policy.socket_allowed(('203.0.113.40',443)))
