# -*- coding: utf-8 -*-
"""
network_scan.py
Descubrimiento de cámaras en red localPensado para tu caso:Descubrimiento de cámaras en red local (Wi‑Fi/LAN)
- Android (IP Webcam MJPEG): http://<ip>:8080/video
- iPad (RTSP):              rtsp://<ip>:8554/stream

Incluye:
- WS-Discovery (ONVIF) por multicast UDP 3702 (pistas)
- SSDP/UPnP por multicast UDP 1900 (pistas)
- Escaneo rápido de subred buscando puertos típicos (priorizando 8080 y 8554)
- Generación de URLs candidatas para probar en la UI
"""

import ipaddress
import socket
import time
import threading
from contextlib import closing


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def get_local_ipv4_candidates():
    """
    Devuelve IPs IPv4 candidatas del equipo. Usamos el truco UDP connect
    (no envía tráfico real) para obtener la IP de salida.
    """
    ip_list = []
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
            s.connect(("8.8.8.8", 80))
            ip_list.append(s.getsockname()[0])
    except Exception:
        pass

    # Fallback
    if not ip_list:
        # Si no se puede, no inventamos mucho: devolvemos vacío
        return []
    return list(dict.fromkeys(ip_list))


def guess_cidr_from_ip(ip: str):
    """
    Asume /24 por defecto (lo típico en redes domésticas/SMB).
    """
    try:
        return ipaddress.IPv4Network(f"{ip}/24", strict=False)
    except Exception:
        return ipaddress.IPv4Network("192.168.1.0/24")


def is_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    """
    Comprueba TCP connect rápido.
    """
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


# ----------------------------------------------------------------------
# WS-Discovery (ONVIF) - pistas
# ----------------------------------------------------------------------
def ws_discovery(timeout: float = 2.0):
    """
    Envia un Probe WS-Discovery (UDP multicast) para ONVIF.
    Devuelve lista de (ip, info_string).
    """
    # Probe mínimo, sin dependencias SOAP
    message = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        b'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        b'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        b'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        b'<e:Header>'
        b'<w:MessageID>uuid:00000000-0000-0000-0000-000000000000</w:MessageID>'
        b'<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        b'<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
        b'</e:Header>'
        b'<e:Body>'
        b'<d:Probe>'
        b'<d:Types>dn:NetworkVideoTransmitter</d:Types>'
        b'</d:Probe>'
        b'</e:Body>'
        b'</e:Envelope>'
    )

    group = ("239.255.255.250", 3702)
    results = []

    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        except Exception:
            pass

        s.settimeout(timeout)
        try:
            s.sendto(message, group)
        except Exception:
            return []

        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (addr, _) = s.recvfrom(8192)
                # Simple heurística: si llega algo, lo tomamos como pista
                if data:
                    results.append((addr, "WS-Discovery response"))
            except socket.timeout:
                break
            except Exception:
                break

    # Dedup
    seen = set()
    out = []
    for ip, info in results:
        if ip not in seen:
            seen.add(ip)
            out.append((ip, info))
    return out


# ----------------------------------------------------------------------
# SSDP (UPnP) - pistas
# ----------------------------------------------------------------------
def ssdp_discover(st: str = "ssdp:all", timeout: float = 2.0):
    """
    M-SEARCH SSDP en multicast UDP 1900.
    Devuelve lista de (ip, server|st).
    """
    msg = "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        "HOST: 239.255.255.250:1900",
        f"ST: {st}",
        'MAN: "ssdp:discover"',
        "MX: 1",
        "", ""
    ]).encode("utf-8")

    addr = ("239.255.255.250", 1900)
    results = []

    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)) as s:
        s.settimeout(timeout)
        try:
            s.sendto(msg, addr)
        except Exception:
            return []

        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (rip, _) = s.recvfrom(8192)
                txt = data.decode("utf-8", errors="ignore")
                server = ""
                st_hdr = ""
                for line in txt.split("\r\n"):
                    if line.lower().startswith("server:"):
                        server = line.split(":", 1)[1].strip()
                    if line.lower().startswith("st:"):
                        st_hdr = line.split(":", 1)[1].strip()
                results.append((rip, server or st_hdr or "SSDP response"))
            except socket.timeout:
                break
            except Exception:
                break

    # Dedup
    seen = set()
    out = []
    for ip, info in results:
        if ip not in seen:
            seen.add(ip)
            out.append((ip, info))
    return out


# ----------------------------------------------------------------------
# Escaneo de subred
# ----------------------------------------------------------------------
# Prioriza tus puertos
COMMON_PORTS = [8080, 8554, 554, 80, 8000, 8888, 1935]


def scan_subnet(cidr: str, max_hosts: int = 256, timeout: float = 0.35):
    """
    Escanea una subred en paralelo y devuelve dict {ip: [puertos_abiertos]}.

    IMPORTANTE: consideramos 'alive' un host si responde en cualquiera de:
    8080 (Android), 8554 (iPad), 554 (RTSP genérico), 80 (HTTP).
    """
    net = ipaddress.IPv4Network(cidr, strict=False)
    hosts = list(net.hosts())
    if len(hosts) > max_hosts:
        hosts = hosts[:max_hosts]

    alive = []
    alive_lock = threading.Lock()

    # ✅ Puertos clave para tus cámaras
    probe_ports = (8080, 8554, 554, 80)

    def worker(ip_obj):
        ip_str = str(ip_obj)
        if any(is_port_open(ip_str, p, timeout) for p in probe_ports):
            with alive_lock:
                alive.append(ip_str)

    threads = []
    for h in hosts:
        t = threading.Thread(target=worker, args=(h,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout + 0.1)

    inventory = {}
    for ip in alive:
        open_ports = []
        for p in COMMON_PORTS:
            if is_port_open(ip, p, timeout):
                open_ports.append(p)
        inventory[ip] = open_ports

    return inventory


# ----------------------------------------------------------------------
# URLs candidatas (adaptadas a tus cámaras)
# ----------------------------------------------------------------------
def build_candidate_urls(ip: str, open_ports):
    """
    Genera URLs candidatas priorizando:
    - Android: http://ip:8080/video
    - iPad:    rtsp://ip:8554/stream
    """
    urls = []

    # ✅ ANDROID (IP Webcam MJPEG)
    if 8080 in open_ports:
        urls.append(f"http://{ip}:8080/video")          # tu formato
        urls.append(f"http://{ip}:8080/video.mjpeg")    # alternativo
        urls.append(f"http://{ip}:8080/")               # panel web

    # ✅ iPAD RTSP (tu formato)
    if 8554 in open_ports:
        urls.append(f"rtsp://{ip}:8554/stream")         # tu formato
        urls.append(f"rtsp://{ip}:8554/live")           # alternativo
        urls.append(f"rtsp://{ip}:8554/")               # fallback

    # RTSP genérico (cámaras IP/ONVIF típicas)
    if 554 in open_ports:
        urls.append(f"rtsp://{ip}:554/stream")
        urls.append(f"rtsp://{ip}:554/live")
        urls.append(f"rtsp://{ip}:554/")

    # HTTP genérico
    if 80 in open_ports:
        urls.append(f"http://{ip}/video")
        urls.append(f"http://{ip}/mjpeg")

    # Dedup preservando orden
    return list(dict.fromkeys(urls))


# ----------------------------------------------------------------------
# API principal usada por la UI
# ----------------------------------------------------------------------
def discover_cameras(auto_iface: bool = True, cidr_hint: str = None):
    """
    Devuelve lista de dicts:
      {
        "ip": "192.168.1.108",
        "ports": [8080],
        "evidence": ["ssdp:...", "onvif:..."],
        "candidates": ["http://.../video", ...]
      }
    """
    # 1) Pistas multicast (no bloqueantes)
    onvif = ws_discovery(timeout=2.0)
    ssdp = ssdp_discover(st="ssdp:all", timeout=2.0)

    # 2) Subred/es a escanear
    subnets = []
    if cidr_hint:
        try:
            subnets = [ipaddress.IPv4Network(cidr_hint, strict=False)]
        except Exception:
            subnets = []
    elif auto_iface:
        for ip in get_local_ipv4_candidates():
            subnets.append(guess_cidr_from_ip(ip))

    # 3) Agregación
    found = {}

    def ensure(ip):
        found.setdefault(ip, {"evidence": [], "ports": []})

    for ip, info in onvif:
        ensure(ip)
        found[ip]["evidence"].append(f"onvif:{info}")

    for ip, info in ssdp:
        ensure(ip)
        found[ip]["evidence"].append(f"ssdp:{info}")

    # 4) Escaneo TCP rápido de subred
    for net in subnets:
        inv = scan_subnet(str(net), max_hosts=min(net.num_addresses, 256), timeout=0.35)
        for ip, ports in inv.items():
            ensure(ip)
            found[ip]["ports"] = sorted(list(set(found[ip]["ports"] + ports)))

    # 5) Construye respuesta
    results = []
    for ip, meta in found.items():
        candidates = build_candidate_urls(ip, meta["ports"])
        # Solo devolvemos los que tengan candidatas útiles
        if candidates:
            results.append({
                "ip": ip,
                "ports": meta["ports"],
                "evidence": meta["evidence"],
                "candidates": candidates,
            })

    # Orden: primero los que tengan 8080/8554, luego por nº puertos
    def score(r):
        ports = set(r.get("ports", []))
        return (
            1 if 8080 in ports else 0,
            1 if 8554 in ports else 0,
            len(ports),
        )

    results.sort(key=lambda r: (score(r)[0], score(r)[1], score(r)[2], r["ip"]), reverse=True)
    return results


# ----------------------------------------------------------------------
# CLI simple para probar
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    hint = sys.argv[1] if len(sys.argv) > 1 else None
    cams = discover_cameras(auto_iface=True, cidr_hint=hint)
    for c in cams:
        print("IP:", c["ip"])
        print("  Puertos:", c["ports"])
        if c["evidence"]:
            print("  Pistas:", c["evidence"])
        print("  URLs:")
        for u in c["candidates"]:
            print("   -", u)
        print()

