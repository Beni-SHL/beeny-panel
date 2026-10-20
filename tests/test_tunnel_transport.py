"""Opt-in real upstream FRP smoke tests, entirely on localhost, no root needed.

BEENY_FRP_TEST_BIN=/path/to/verified/frp python -m unittest discover -s tests -p test_tunnel_transport.py
"""
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import tunnel_manager as manager

class TCP(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            blob=self.request.recv(65536)
            if not blob:return
            self.request.sendall(blob)

class UDP(socketserver.BaseRequestHandler):
    def handle(self):
        blob,sock=self.request;sock.sendto(blob,self.client_address)

def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET,kind) as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

@unittest.skipUnless(os.environ.get('BEENY_FRP_TEST_BIN'),'requires explicitly supplied verified FRP binaries')
class RealTransportTests(unittest.TestCase):
    def test_untrusted_entry_certificate_cannot_register(self):
        bindir=Path(os.environ['BEENY_FRP_TEST_BIN'])
        with tempfile.TemporaryDirectory() as temp,patch.object(manager,'ROOT',Path(temp)):
            pem,key=manager.cert();wrong,_=manager.cert()
            v=manager.validate_invitation(dict(version=1,host='127.0.0.1',control_port=free_port(),public_port=free_port(),mode='tls',token='a'*64,ca=pem))
            pair=dict(role='exit',invitation=v,listener=dict(proto='tcp',port=free_port()))
            for name,text in [('server.crt',pem),('server.key',key),('ca.crt',wrong),('frps.toml',manager.config_entry(v)),('frpc.toml',manager.config_exit(v,pair['listener']))]:manager.write(name,text)
            env={k:v for k,v in os.environ.items() if k.lower() not in {'http_proxy','https_proxy','all_proxy'}}
            processes=[]
            try:
                for name in ['frps','frpc']:
                    processes.append(subprocess.Popen([str(bindir/name),'-c',str(Path(temp)/(name+'.toml'))],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
                time.sleep(1)
                with patch.object(manager,'active',return_value=True):self.assertFalse(manager.registered(pair))
            finally:
                for process in reversed(processes):process.terminate();process.wait(timeout=4)

    def test_six_transport_and_payload_combinations(self):
        for mode in ['tls','ws-tls','quic']:
            for proto in ['tcp','udp']:
                with self.subTest(mode=mode,proto=proto):self.exercise(mode,proto)

    def exercise(self,mode,proto):
        bindir=Path(os.environ['BEENY_FRP_TEST_BIN'])
        with tempfile.TemporaryDirectory() as temp,patch.object(manager,'ROOT',Path(temp)):
            target=(socketserver.ThreadingTCPServer if proto=='tcp' else socketserver.ThreadingUDPServer)(('127.0.0.1',0),TCP if proto=='tcp' else UDP)
            thread=threading.Thread(target=target.serve_forever,daemon=True);thread.start()
            pem,key=manager.cert()
            v=manager.validate_invitation(dict(version=1,host='127.0.0.1',control_port=free_port(),public_port=free_port(socket.SOCK_STREAM if proto=='tcp' else socket.SOCK_DGRAM),mode=mode,token='b'*64,ca=pem))
            pair=dict(role='exit',invitation=v,listener=dict(proto=proto,port=target.server_address[1]))
            for name,text in [('server.crt',pem),('server.key',key),('ca.crt',pem),('frps.toml',manager.config_entry(v)),('frpc.toml',manager.config_exit(v,pair['listener']))]:manager.write(name,text)
            processes=[]
            try:
                for name in ['frps','frpc']:
                    command=[str(bindir/name),'-c',str(Path(temp)/(name+'.toml'))]
                    checked=subprocess.run([str(bindir/name),'verify','-c',str(Path(temp)/(name+'.toml'))],capture_output=True,text=True)
                    self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
                    env={k:v for k,v in os.environ.items() if k.lower() not in {'http_proxy','https_proxy','all_proxy'}}
                    processes.append(subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env))
                with patch.object(manager,'active',return_value=True):
                    until=time.monotonic()+12
                    while not manager.registered(pair) and time.monotonic()<until:time.sleep(.15)
                    self.assertTrue(manager.registered(pair),'proxy registration failed for '+mode+'/'+proto)
                if proto=='tcp':
                    data=os.urandom(65536)
                    with socket.create_connection(('127.0.0.1',v['public_port']),timeout=3) as sock:
                        sock.sendall(data);output=b''
                        while len(output)<len(data):output+=sock.recv(65536)
                        self.assertEqual(output,data)
                else:
                    data=os.urandom(1800)
                    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                        sock.settimeout(3);sock.sendto(data,('127.0.0.1',v['public_port']))
                        self.assertEqual(sock.recv(4096),data)
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:process.wait(timeout=4)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                target.shutdown();target.server_close();thread.join(timeout=2)
