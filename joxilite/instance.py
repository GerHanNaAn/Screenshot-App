import hashlib
import json
import os
import getpass
from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance:
    def __init__(self,callback):
        identity="com.german.joxilite-"+hashlib.sha256(getpass.getuser().encode()).hexdigest()[:12]
        self.name=identity
        path=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        self.lock=QLockFile(os.path.join(path,identity+".lock")); self.lock.setStaleLockTime(0)
        self.primary=self.lock.tryLock(0)
        self.server=None; self.connections=[]
        if self.primary:
            QLocalServer.removeServer(identity)
            self.server=QLocalServer(); self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            if not self.server.listen(identity): raise RuntimeError(self.server.errorString())
            self.server.newConnection.connect(lambda:self.accept(callback))

    def accept(self,callback):
        connection=self.server.nextPendingConnection(); self.connections.append(connection)
        data=bytearray()
        def read():
            import shiboken6
            isValid = shiboken6.isValid
            if not isValid(connection): return
            data.extend(bytes(connection.readAll()))
            if len(data)>65536: connection.abort(); return
            if b"\n" not in data: return
            if not isValid(connection): return
            connection.write(b"OK\n"); connection.flush()
            try: callback(json.loads(data.split(b"\n",1)[0]))
            except (ValueError,TypeError): pass
            if isValid(connection): connection.disconnectFromServer()
        connection.readyRead.connect(read)
        def disconnected():
            if connection in self.connections: self.connections.remove(connection)
            connection.deleteLater()
        connection.disconnected.connect(disconnected)
        if connection.bytesAvailable(): read()

    def send(self,message):
        socket=QLocalSocket(); socket.connectToServer(self.name)
        if not socket.waitForConnected(3000): raise RuntimeError("Работающий JoxiLite не отвечает. Повторите запуск.")
        socket.write(json.dumps(message).encode()+b"\n"); socket.flush(); socket.waitForBytesWritten(3000)
        if not socket.waitForReadyRead(3000): raise RuntimeError("JoxiLite не подтвердил команду.")
        socket.disconnectFromServer()

    def close(self):
        if self.server: self.server.close()
        if self.primary: self.lock.unlock()
