"""Local dependency bootstrap workaround for the host's unavailable DNS server.
Only this subprocess uses fixed CDN addresses; no system network settings change.
"""
import socket, sys, runpy
original = socket.getaddrinfo
addresses = {"pypi.org":"151.101.0.223", "files.pythonhosted.org":"151.101.0.223"}
def resolved(host,*args,**kwargs):
    return original(addresses.get(host,host),*args,**kwargs)
socket.getaddrinfo = resolved
sys.argv = ["pip"]+sys.argv[1:]
runpy.run_module("pip",run_name="__main__")
