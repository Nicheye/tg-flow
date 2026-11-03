from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re, subprocess, threading

session='tgflow-consent-check'
received=threading.Event()
class Callback(BaseHTTPRequestHandler):
 def do_GET(self):
  received.set(); self.send_response(200);self.end_headers();self.wfile.write(b'OAuth callback reached')
 def log_message(self,*args):pass
callback=ThreadingHTTPServer(('127.0.0.1',0),Callback)
callback_origin=f'http://127.0.0.1:{callback.server_port}'
template=(Path(__file__).resolve().parents[3] / 'tg_flow_bot/users/templates/oauth/consent.html').read_text()
policy=re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"',template).group(1).replace('{{ redirect_csp_source }}',callback_origin)
class Consent(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
  self.wfile.write(('<html><head><meta http-equiv="Content-Security-Policy" content="'+policy+'"></head><body><form method="post" action="/decision"><button type="submit">Allow</button></form></body></html>').encode())
 def do_POST(self):
  self.send_response(302);self.send_header('Location',callback_origin+'/callback');self.end_headers()
 def log_message(self,*args):pass
consent=ThreadingHTTPServer(('127.0.0.1',0),Consent)
for server in [callback,consent]:threading.Thread(target=server.serve_forever,daemon=True).start()
def browser(*args):
 r=subprocess.run(['agent-browser','--session',session,*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 if r.returncode:print(r.stdout)
 return r
try:
 browser('open',f'http://127.0.0.1:{consent.server_port}')
 browser('snapshot','-i')
 browser('find','role','button','click','--name','Allow')
 assert received.wait(2), 'Consent form CSP blocked the external OAuth callback redirect'
 print('Consent form permits the registered external callback: PASS')
finally:
 browser('close')
 for server in [callback,consent]:server.shutdown();server.server_close()
