"""Logging CONNECT proxy for DG-00.04: records the host and port of every outbound HTTPS
connection Auto Ontology opens, without decrypting it, then tunnels through UPSTREAM (the
session's own proxy) or directly when UPSTREAM is unset.

  UPSTREAM=127.0.0.1:38189 python egress_log.py 127.0.0.1:38999 egress.jsonl
"""
import asyncio
import datetime
import json
import os
import sys


async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        w.close()


async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter, log) -> None:
    head = await cr.readuntil(b"\r\n\r\n")
    method, target, _ = head.split(b"\r\n", 1)[0].decode().split(" ", 2)
    log.write(json.dumps({"at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                          "method": method, "target": target}) + "\n")
    log.flush()
    if method != "CONNECT":
        cw.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
        cw.close()
        return
    up = os.environ.get("UPSTREAM")
    if up:
        host, port = up.rsplit(":", 1)
        ur, uw = await asyncio.open_connection(host, int(port))
        uw.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        await uw.drain()
        reply = await ur.readuntil(b"\r\n\r\n")
        cw.write(reply)
        if b" 200" not in reply.split(b"\r\n", 1)[0]:
            cw.close()
            return
    else:
        host, port = target.rsplit(":", 1)
        ur, uw = await asyncio.open_connection(host, int(port))
        cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await cw.drain()
    await asyncio.gather(pipe(cr, uw), pipe(ur, cw))


async def main() -> None:
    host, port = sys.argv[1].rsplit(":", 1)
    with open(sys.argv[2], "a") as log:
        server = await asyncio.start_server(lambda r, w: handle(r, w, log), host, int(port))
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
