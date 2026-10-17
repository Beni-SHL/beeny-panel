"""Client for the fixed-operation root helper. No shell or arbitrary paths."""
import json, os, socket

def call(operation, **parameters):
    address=os.environ.get('BEENY_PRIVILEGE_SOCKET','/run/beeny-panel/privileged.sock')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(125);client.connect(address)
        client.sendall(json.dumps(dict(operation=operation,parameters=parameters)).encode()+b'\n')
        with client.makefile('rb') as stream:result=json.loads(stream.readline(4*1024*1024))
    if not result.get('ok'):raise RuntimeError(result.get('error','Privileged operation failed.'))
    return result.get('result')

def enabled():return bool(os.environ.get('BEENY_PRIVILEGE_SOCKET'))
