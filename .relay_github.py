import socket
import threading

LISTEN = ('127.0.0.1', 18765)
TARGETS = [('140.82.113.3', 443), ('20.27.177.113', 443)]
TARGET = TARGETS[0]


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def handle(client):
    buf = b''
    while b'\r\n\r\n' not in buf:
        chunk = client.recv(4096)
        if not chunk:
            client.close()
            return
        buf += chunk
    head, rest = buf.split(b'\r\n\r\n', 1)
    first = head.split(b'\r\n', 1)[0].decode('latin-1', 'replace')
    if not first.upper().startswith('CONNECT'):
        client.sendall(b'HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n')
        client.close()
        return
    upstream = None
    for host, port in TARGETS:
        try:
            upstream = socket.create_connection((host, port), timeout=20)
            break
        except OSError:
            upstream = None
    if upstream is None:
        client.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
        client.close()
        return
    client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
    if rest:
        upstream.sendall(rest)
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    pipe(upstream, client)


def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(32)
    print('relay listening on %s:%d -> %s' % (LISTEN[0], LISTEN[1], TARGETS), flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


main()
