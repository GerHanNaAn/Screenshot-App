"""Wayland uses consent-based desktop portals; no bypass of compositor permissions."""
import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage
from . import Frame

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"


class Portal:
    async def connect(self):
        from dbus_next.aio import MessageBus
        self.bus = await MessageBus(negotiate_unix_fd=True).connect()
        node = await self.bus.introspect(BUS,PATH)
        self.object = self.bus.get_proxy_object(BUS,PATH,node)
        return self

    async def request(self, method, *args, **options):
        from dbus_next import Variant
        token = "joxi"+uuid.uuid4().hex
        options["handle_token"] = Variant("s",token)
        sender = self.bus.unique_name[1:].replace(".","_")
        expected = f"{PATH}/request/{sender}/{token}"
        # Subscribe before invoking the method: fast portals may respond before the method reply.
        from dbus_next import Message, MessageType
        match = f"type='signal',interface='org.freedesktop.portal.Request',member='Response',path='{expected}'"
        await self.bus.call(Message(destination="org.freedesktop.DBus",path="/org/freedesktop/DBus",
                                    interface="org.freedesktop.DBus",member="AddMatch",signature="s",body=[match]))
        future = asyncio.get_running_loop().create_future()
        def handle(message):
            if message.message_type == MessageType.SIGNAL and message.path == expected and message.member == "Response":
                if not future.done(): future.set_result(message.body)
        self.bus.add_message_handler(handle)
        try:
            request_path = await method(*args,options)
            if request_path != expected:
                raise RuntimeError("Портал вернул неожиданный дескриптор запроса.")
            status,result = await asyncio.wait_for(future,120)
            if status == 1: raise RuntimeError("Захват отменён в системном диалоге.")
            if status: raise RuntimeError(f"Портал рабочего стола отказал в запросе ({status}).")
            return result
        except asyncio.TimeoutError:
            await self.bus.call(Message(destination=BUS,path=expected,interface="org.freedesktop.portal.Request",member="Close"))
            raise RuntimeError("Истекло время ожидания разрешения в системном диалоге.")
        finally:
            self.bus.remove_message_handler(handle)
            await self.bus.call(Message(destination="org.freedesktop.DBus",path="/org/freedesktop/DBus",
                                        interface="org.freedesktop.DBus",member="RemoveMatch",signature="s",body=[match]))

    async def close_session(self, path):
        from dbus_next import Message
        await self.bus.call(Message(destination=BUS,path=path,interface="org.freedesktop.portal.Session",member="Close"))


async def capture(window=False, cursor=False):
    from dbus_next import Variant
    from dbus_next import Message
    portal = await Portal().connect()
    session = None
    fd = None
    try:
        if not shutil.which("gst-launch-1.0"):
            raise RuntimeError("Для Wayland установите gstreamer1.0-tools, gstreamer1.0-pipewire и gstreamer1.0-plugins-good.")
        interface = portal.object.get_interface("org.freedesktop.portal.ScreenCast")
        result = await portal.request(interface.call_create_session, session_handle_token=Variant("s","joxi"+uuid.uuid4().hex))
        session = result["session_handle"].value
        cursor_modes = await interface.get_available_cursor_modes()
        cursor_mode = 2 if cursor else 1
        if not cursor_modes&cursor_mode:
            raise RuntimeError("Системный портал не поддерживает выбранный режим курсора.")
        await portal.request(interface.call_select_sources, session, types=Variant("u",2 if window else 1),
                             multiple=Variant("b",False), cursor_mode=Variant("u",cursor_mode))
        result = await portal.request(interface.call_start,session,"")
        streams = result["streams"].value
        if not streams: raise RuntimeError("Портал не предоставил экран или окно.")
        # Raw call retains the transferred FD; dbus-next proxy converts only the handle index.
        response = await portal.bus.call(Message(destination=BUS,path=PATH,interface="org.freedesktop.portal.ScreenCast",
                                                  member="OpenPipeWireRemote",signature="oa{sv}",body=[session,{}]))
        if not response.unix_fds: raise RuntimeError("Портал не предоставил соединение PipeWire.")
        fd = response.unix_fds[response.body[0]]
        node,properties = streams[0]
        with tempfile.TemporaryDirectory(prefix="JoxiLite-pipewire-") as directory:
            path = Path(directory)/"frame.png"
            command = ["gst-launch-1.0","-q","pipewiresrc",f"fd={fd}",f"path={node}","num-buffers=1","!",
                       "videoconvert","!","pngenc","snapshot=true","!","filesink",f"location={path}"]
            # Run outside the asyncio loop: keep the portal connection/session alive while reading.
            process = await asyncio.to_thread(subprocess.run,command,pass_fds=(fd,),capture_output=True,timeout=30)
            if process.returncode: raise RuntimeError(process.stderr.decode(errors="replace"))
            image = QImage(str(path))
            if image.isNull(): raise RuntimeError("PipeWire не вернул изображение.")
            size = properties.get("size")
            position = properties.get("position")
            if size and position:
                geometry = QRect(*position.value,*size.value)
            else:
                geometry = QRect(0,0,image.width(),image.height())
            return [Frame(image,geometry,"Wayland")]
    finally:
        if fd is not None: os.close(fd)
        if session: await portal.close_session(session)
        portal.bus.disconnect()


class PortalHotkeys:
    def __init__(self, callback):
        self.callback, self.loop, self.portal, self.session = callback, None, None, None
        self.thread = threading.Thread(target=self._run,daemon=True)
        self.ready = threading.Event()
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()

    def register(self, keys):
        # Binding includes a system dialog; don't block the Qt UI while the user chooses shortcuts.
        future = asyncio.run_coroutine_threadsafe(self._bind(keys),self.loop)
        def finished(result):
            try: result.result()
            except Exception as error: self.callback("error:"+str(error))
        future.add_done_callback(finished)
        return []

    async def _bind(self, keys):
        from dbus_next import Variant
        await self._clear()
        self.portal = await Portal().connect()
        try:
            interface = self.portal.object.get_interface("org.freedesktop.portal.GlobalShortcuts")
        except Exception:
            self.portal.bus.disconnect()
            self.portal = None
            raise RuntimeError("Рабочий стол Wayland не предоставляет GlobalShortcuts. Назначьте команду «JoxiLite --capture area» в системных настройках клавиатуры.")
        result = await self.portal.request(interface.call_create_session,
                                          session_handle_token=Variant("s","joxi"+uuid.uuid4().hex))
        self.session = result["session_handle"].value
        from ..document import TOOLS
        titles = {"area":"Область","window":"Окно","screen":"Экран","delayed":"Экран с задержкой"}
        shortcuts = [(action,{"description":Variant("s",titles[action]),
                    "preferred_trigger":Variant("s",key.replace("Ctrl+","CTRL+").replace("Meta+","LOGO+").replace("Alt+","ALT+").replace("Shift+","SHIFT+"))})
                     for action,key in keys.items() if key]
        def activated(session,identifier,timestamp,options):
            if session == self.session: self.callback(identifier)
        interface.on_activated(activated)
        await self.portal.request(interface.call_bind_shortcuts,self.session,shortcuts,"")

    async def _clear(self):
        if self.portal:
            if self.session: await self.portal.close_session(self.session)
            self.portal.bus.disconnect()
        self.portal,self.session = None,None

    def clear(self):
        if self.loop: asyncio.run_coroutine_threadsafe(self._clear(),self.loop)

    def close(self):
        if self.loop:
            try: asyncio.run_coroutine_threadsafe(self._clear(),self.loop).result(5)
            except Exception: pass
            self.loop.call_soon_threadsafe(self.loop.stop)
