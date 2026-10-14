"""Wayland uses consent-based desktop portals; no bypass of compositor permissions."""
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from .. import APP_ID
from . import Frame

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"


def allow_portal_names():
    """GNOME portals expose hyphenated property names. dbus-next 0.2.3 rejects them."""
    import dbus_next.introspection as introspection
    from dbus_next.errors import InvalidMemberNameError
    if getattr(introspection, "_joxilite_names", False):
        return
    original = introspection.assert_member_name_valid

    def accept(name):
        try:
            original(name)
        except InvalidMemberNameError:
            if name and all(character.isalnum() or character in "-_" for character in name):
                return
            raise

    introspection.assert_member_name_valid = accept
    introspection._joxilite_names = True


class Portal:
    async def connect(self):
        allow_portal_names()
        from dbus_next.aio import MessageBus
        self.bus = await MessageBus(negotiate_unix_fd=True).connect()
        node = await self.bus.introspect(BUS, PATH)
        self.object = self.bus.get_proxy_object(BUS, PATH, node)
        await self.register_host_app()
        return self

    async def register_host_app(self):
        try:
            registry = self.object.get_interface("org.freedesktop.host.portal.Registry")
            await registry.call_register(APP_ID, {})
        except Exception as error:
            logging.warning("Не удалось зарегистрировать приложение в портале: %s", error)

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
            if status == 2:
                raise RuntimeError("GNOME не показал запрос доступа к экрану: окно JoxiLite должно быть на переднем плане. Откройте JoxiLite и повторите снимок, затем разрешите доступ.")
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


def _ints(value):
    raw = value.value if hasattr(value, "value") else value
    return [int(item) for item in raw]


def _stream_geometry(properties, image):
    size = properties.get("size") if properties else None
    position = properties.get("position") if properties else None
    if size and position:
        x, y = _ints(position)
        width, height = _ints(size)
        return QRect(x, y, width, height)
    return QRect(0, 0, image.width(), image.height())


async def _pipewire_png(fd, node, path):
    if not shutil.which("gst-launch-1.0"):
        raise RuntimeError("Для захвата окна на Wayland установите gstreamer1.0-tools, gstreamer1.0-pipewire и gstreamer1.0-plugins-good.")
    attempts = (
        ["gst-launch-1.0", "-e", "pipewiresrc", f"fd={fd}", f"target-object={node}", "num-buffers=1", "!",
         "videoconvert", "!", "pngenc", "!", "filesink", f"location={path}"],
        ["gst-launch-1.0", "-e", "pipewiresrc", f"fd={fd}", f"path={node}", "num-buffers=1", "!",
         "videoconvert", "!", "pngenc", "snapshot=true", "!", "filesink", f"location={path}"],
    )
    errors = []
    for command in attempts:
        if path.exists():
            path.unlink()
        process = await asyncio.to_thread(subprocess.run, command, pass_fds=(fd,), capture_output=True, timeout=20)
        if process.returncode == 0 and path.exists() and path.stat().st_size > 32:
            return
        errors.append(process.stderr.decode(errors="replace")[-400:])
    raise RuntimeError("PipeWire не вернул изображение.\n" + "\n".join(errors))


async def screenshot_desktop():
    """One still image of the desktop. GNOME returns every monitor in a single PNG."""
    from dbus_next import Variant
    portal = await Portal().connect()
    try:
        interface = portal.object.get_interface("org.freedesktop.portal.Screenshot")
        result = await portal.request(interface.call_screenshot, "", interactive=Variant("b", False), modal=Variant("b", True))
        from urllib.parse import unquote, urlparse
        path = unquote(urlparse(result["uri"].value).path)
        image = QImage(path)
        if image.isNull():
            raise RuntimeError("Портал снимка экрана вернул пустой файл.")
        image = image.copy()
        image.setDevicePixelRatio(1)
        return image
    finally:
        portal.bus.disconnect()


async def capture(window=False, cursor=False):
    if not window:
        image = await screenshot_desktop()
        return [Frame(image, QRect(0, 0, image.width(), image.height()), "Wayland")]
    from dbus_next import Variant, Message
    portal = await Portal().connect()
    session = None
    fd = None
    try:
        interface = portal.object.get_interface("org.freedesktop.portal.ScreenCast")
        result = await portal.request(interface.call_create_session, session_handle_token=Variant("s", "joxi" + uuid.uuid4().hex))
        session = result["session_handle"].value
        cursor_modes = await interface.get_available_cursor_modes()
        cursor_mode = 2 if cursor and cursor_modes & 2 else 1
        await portal.request(interface.call_select_sources, session, types=Variant("u", 2),
                             multiple=Variant("b", False), cursor_mode=Variant("u", cursor_mode),
                             persist_mode=Variant("u", 2))
        result = await portal.request(interface.call_start, session, "")
        streams = result["streams"].value
        if not streams:
            raise RuntimeError("Портал не предоставил окно.")
        response = await portal.bus.call(Message(destination=BUS, path=PATH, interface="org.freedesktop.portal.ScreenCast",
                                                  member="OpenPipeWireRemote", signature="oa{sv}", body=[session, {}]))
        if not response.unix_fds:
            raise RuntimeError("Портал не предоставил соединение PipeWire.")
        fd = response.unix_fds[response.body[0]]
        frames = []
        with tempfile.TemporaryDirectory(prefix="JoxiLite-pipewire-") as directory:
            for index, stream in enumerate(streams):
                node, properties = stream
                path = Path(directory) / f"frame-{index}.png"
                await _pipewire_png(fd, node, path)
                image = QImage(str(path))
                if image.isNull():
                    raise RuntimeError("PipeWire не вернул изображение.")
                frames.append(Frame(image, _stream_geometry(properties, image), "Окно"))
        return frames
    finally:
        if fd is not None:
            os.close(fd)
        if session:
            await portal.close_session(session)
        portal.bus.disconnect()


def gtk_accelerator(sequence):
    """Qt portable text (Ctrl+Alt+2) to the GTK form GNOME stores (<Control><Alt>2)."""
    parts = sequence.split("+")
    modifiers = {"Ctrl": "<Control>", "Alt": "<Alt>", "Shift": "<Shift>", "Meta": "<Super>"}
    key = parts[-1]
    if len(key) == 1 and key.isalpha():
        key = key.lower()
    return "".join(modifiers[part] for part in parts[:-1]) + key


def same_accelerator(left, right):
    """GNOME may store <Shift><Control>1 for the same chord as <Control><Shift>1."""
    def parts(accelerator):
        modifiers = []
        rest = accelerator
        while rest.startswith("<"):
            end = rest.find(">")
            modifiers.append(rest[1:end])
            rest = rest[end + 1:]
        return frozenset(modifiers), rest.lower()
    return parts(left) == parts(right)


def updated_gnome_shortcuts(stored, keys):
    """GNOME reuses a saved trigger and ignores a later preferred_trigger for the same id."""
    saved = {action: dict(props) for action, props in stored}
    changed = False
    for action, sequence in keys.items():
        if action not in saved or not sequence:
            continue
        accelerator = gtk_accelerator(sequence)
        current = list(saved[action].get("shortcuts") or [])
        if len(current) != 1 or not same_accelerator(current[0], accelerator):
            saved[action]["shortcuts"] = [accelerator]
            changed = True
    return [(action, props) for action, props in saved.items()], changed


def sync_gnome_saved_shortcuts(keys):
    if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
        return
    try:
        from gi.repository import Gio, GLib
    except Exception as error:
        logging.warning("Не удалось обновить сочетания GNOME: %s", error)
        return
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup("org.gnome.settings-daemon.global-shortcuts.application", True) is None:
        return
    settings = Gio.Settings.new_with_path(
        "org.gnome.settings-daemon.global-shortcuts.application",
        f"/org/gnome/settings-daemon/global-shortcuts/{APP_ID}/")
    updated, changed = updated_gnome_shortcuts(settings.get_value("shortcuts").unpack(), keys)
    if not changed:
        return
    payload = []
    for action, props in updated:
        values = {}
        for name, value in props.items():
            if isinstance(value, str):
                values[name] = GLib.Variant("s", value)
            else:
                values[name] = GLib.Variant("as", [str(item) for item in value])
        payload.append((action, values))
    settings.set_value("shortcuts", GLib.Variant("a(sa{sv})", payload))


_UNBIND = object()


class PortalHotkeys:
    def __init__(self, callback):
        self.callback, self.loop, self.portal, self.session = callback, None, None, None
        self._mutex = threading.Lock()
        self._pending = None
        self._scheduled = False
        self._closed = False
        self._busy = None
        self.thread = threading.Thread(target=self._run,daemon=True)
        self.ready = threading.Event()
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._busy = asyncio.Lock()
        self.ready.set()
        self.loop.run_forever()

    def register(self, keys):
        # Saving settings binds twice in a row. Keep the latest request and finish it once.
        self._submit(dict(keys))
        return []

    def clear(self):
        self._submit(_UNBIND)

    def _submit(self, pending):
        if not self.loop or self._closed:
            return
        with self._mutex:
            self._pending = pending
            if self._scheduled:
                return
            self._scheduled = True
        asyncio.run_coroutine_threadsafe(self._drain(), self.loop)

    async def _drain(self):
        while not self._closed:
            with self._mutex:
                pending = self._pending
                self._pending = None
                if pending is None:
                    self._scheduled = False
                    return
            try:
                if pending is _UNBIND:
                    await self._release()
                else:
                    await self._bind(pending)
            except Exception as error:
                self.callback("error:" + str(error))

    async def _bind(self, keys):
        from dbus_next import Variant
        async with self._busy:
            if self._closed:
                return
            sync_gnome_saved_shortcuts(keys)
            await self._release_unlocked()
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
            titles = {"area":"Область","window":"Окно","screen":"Экран","delayed":"Экран с задержкой"}
            shortcuts = [[action, {"description": Variant("s", titles[action]),
                         "preferred_trigger": Variant("s", key.replace("Ctrl+", "CTRL+").replace("Meta+", "LOGO+").replace("Alt+", "ALT+").replace("Shift+", "SHIFT+"))}]
                         for action, key in keys.items() if key]
            def activated(session,identifier,timestamp,options):
                if session == self.session: self.callback(identifier)
            interface.on_activated(activated)
            await self.portal.request(interface.call_bind_shortcuts,self.session,shortcuts,"")

    async def _release_unlocked(self):
        portal, session = self.portal, self.session
        self.portal, self.session = None, None
        if not portal:
            return
        try:
            if session:
                await portal.close_session(session)
        except Exception:
            pass
        try:
            portal.bus.disconnect()
        except Exception:
            pass

    async def _release(self):
        async with self._busy:
            await self._release_unlocked()

    def close(self):
        if not self.loop:
            return
        self._closed = True
        try:
            asyncio.run_coroutine_threadsafe(self._release(), self.loop).result(5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
